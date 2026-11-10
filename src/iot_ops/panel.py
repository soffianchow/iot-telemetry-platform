"""Manual sensor panel: operator-driven devices that publish only on request."""
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
from .mqtt import BufferedPublisher
from .validation import validate

LOG = logging.getLogger(__name__)
UI_PATH = Path(__file__).with_name("panel.html")
MAX_BODY = 4096
LOOPBACK = {"localhost", "127.0.0.1", "::1"}

# Target growing ranges: selecting a crop presets sensors and sets the auto-irrigation threshold.
CROPS = {
    "lettuce": {"temperature_c": [16, 24], "humidity_pct": [50, 70], "soil_moisture_pct": [55, 75], "light_lux": [10000, 25000]},
    "tomato": {"temperature_c": [20, 28], "humidity_pct": [60, 80], "soil_moisture_pct": [50, 70], "light_lux": [25000, 60000]},
    "chili": {"temperature_c": [22, 32], "humidity_pct": [55, 75], "soil_moisture_pct": [45, 65], "light_lux": [30000, 70000]},
    "strawberry": {"temperature_c": [15, 26], "humidity_pct": [60, 75], "soil_moisture_pct": [60, 80], "light_lux": [15000, 40000]},
}
# Schema bounds; inputs are rejected outside them so every reading stays publishable.
LIMITS = {
    "temperature_c": (-50, 100), "humidity_pct": (0, 100), "soil_moisture_pct": (0, 100), "light_lux": (0, 150000),
    "tank_level_pct": (0, 100), "battery_pct": (0, 100), "signal_strength_dbm": (-120, -20),
}
FAULTS = ("anomaly", "sensor_failure", "pump_fault", "offline", "missing")
PUMP_MODES = ("auto", "on", "off")


def clamp(value: float, key: str) -> float:
    low, high = LIMITS[key]
    return max(low, min(high, value))


class ManualDevice:
    def __init__(self, device_id: str, crop: str = "lettuce", start_sequence: int = 0):
        self.device_id = device_id
        self.sequence = start_sequence
        self.settings = {"tank_level_pct": 90.0, "battery_pct": 100.0, "signal_strength_dbm": -62.0, "pump_mode": "auto", "faults": []}
        self.last_payload = None
        self.apply_crop(crop)

    def apply_crop(self, crop: str):
        if not isinstance(crop, str) or crop not in CROPS:
            raise ValueError(f"Unknown crop {crop!r}")
        self.crop = crop
        for key, (low, high) in CROPS[crop].items():
            self.settings[key] = round((low + high) / 2, 2)

    def update(self, changes: dict):
        # Validate everything before mutating so a bad field leaves the device unchanged.
        unknown = set(changes) - set(LIMITS) - {"crop", "pump_mode", "faults"}
        if unknown:
            raise ValueError(f"Unknown fields: {sorted(unknown)}")
        for key in set(changes) & set(LIMITS):
            value = changes[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not LIMITS[key][0] <= value <= LIMITS[key][1]:
                raise ValueError(f"{key} must be a number within {LIMITS[key]}")
        if "pump_mode" in changes and (not isinstance(changes["pump_mode"], str) or changes["pump_mode"] not in PUMP_MODES):
            raise ValueError(f"pump_mode must be one of {PUMP_MODES}")
        faults = changes.get("faults", [])
        if not isinstance(faults, list) or not all(isinstance(f, str) and f in FAULTS for f in faults):
            raise ValueError(f"faults must be a list drawn from {FAULTS}")
        if "crop" in changes:
            self.apply_crop(changes["crop"])
        for key, value in changes.items():
            if key in LIMITS:
                self.settings[key] = float(value)
            elif key == "faults":
                self.settings[key] = sorted(set(value))
            elif key == "pump_mode":
                self.settings[key] = value

    def pump_state(self) -> str:
        settings = self.settings
        if "pump_fault" in settings["faults"]:
            return "fault"
        if settings["tank_level_pct"] <= 0 or settings["pump_mode"] == "off":
            return "off"
        if settings["pump_mode"] == "on":
            return "on"
        return "on" if settings["soil_moisture_pct"] < CROPS[self.crop]["soil_moisture_pct"][0] else "off"

    def reading(self, now: datetime | None = None) -> dict | None:
        settings, faults = self.settings, set(self.settings["faults"])
        sequence = self.sequence
        self.sequence += 1  # Gaps are observable even when a reading is missing.
        pump = self.pump_state()
        payload = None if "missing" in faults else self.payload(sequence, pump, faults, now)
        # Report what the operator set, then apply this step's watering so the next reading shows it.
        if pump == "on":
            settings["soil_moisture_pct"] = clamp(settings["soil_moisture_pct"] + 2.0, "soil_moisture_pct")
            settings["tank_level_pct"] = clamp(settings["tank_level_pct"] - 1.0, "tank_level_pct")
        settings["battery_pct"] = clamp(settings["battery_pct"] - (0.05 if pump == "on" else 0.01), "battery_pct")
        if payload is None:
            return None
        self.last_payload = payload
        return payload

    def payload(self, sequence: int, pump: str, faults: set[str], now: datetime | None) -> dict:
        settings = self.settings
        temperature = None if "sensor_failure" in faults else round(clamp(settings["temperature_c"] + (14 if "anomaly" in faults else 0), "temperature_c"), 2)
        payload = {
            "schema_version": 1, "device_id": self.device_id,
            "timestamp": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sequence": sequence,
            "signal_strength_dbm": round(clamp(settings["signal_strength_dbm"] - (35 if "offline" in faults else 0), "signal_strength_dbm"), 1),
            "connectivity": "offline" if "offline" in faults else "online",
            "metrics": {
                "temperature_c": temperature, "humidity_pct": round(settings["humidity_pct"], 2),
                "soil_moisture_pct": round(settings["soil_moisture_pct"], 2), "light_lux": round(settings["light_lux"], 1),
                "tank_level_pct": round(settings["tank_level_pct"], 2), "pump_state": pump,
                "battery_pct": round(settings["battery_pct"], 3),
            },
            "quality": sorted(faults - {"missing"}),
        }
        validate(payload, f"iot-ops/devices/{self.device_id}/telemetry")
        return payload

    def view(self) -> dict:
        return {"device_id": self.device_id, "crop": self.crop, "settings": self.settings, "pump_state": self.pump_state(), "last_payload": self.last_payload}


class Panel:
    def __init__(self, devices: list[ManualDevice], publishers: BufferedPublisher | dict[str, BufferedPublisher]):
        self.devices = {d.device_id: d for d in devices}
        # One shared connection locally, or one per device when each holds its own certificate.
        self.publishers = publishers if isinstance(publishers, dict) else {i: publishers for i in self.devices}
        self.connections = list({id(p): p for p in self.publishers.values()}.values())
        self.lock = threading.Lock()

    def queued(self) -> int:
        return sum(len(p.pending) for p in self.connections)

    def state(self) -> dict:
        with self.lock:
            return {
                "broker_connected": all(p.connected.is_set() for p in self.connections), "queued": self.queued(),
                "dropped": sum(p.dropped for p in self.connections), "crops": CROPS, "faults": FAULTS, "pump_modes": PUMP_MODES,
                "limits": LIMITS, "devices": [d.view() for d in self.devices.values()],
            }

    def device(self, device_id: str) -> ManualDevice:
        if not isinstance(device_id, str):
            raise ValueError("Device IDs must be strings")
        if device_id not in self.devices:
            raise KeyError(device_id)
        return self.devices[device_id]

    def update(self, device_id: str, changes: dict) -> dict:
        with self.lock:
            device = self.device(device_id)
            device.update(changes)
            return device.view()

    def send(self, device_ids: list[str]) -> list[dict]:
        with self.lock:
            devices = [self.device(i) for i in device_ids]
            sent = [(d, d.reading()) for d in devices]
            for _, payload in sent:
                if payload:
                    self.publishers[payload["device_id"]].enqueue(payload)
            offline = {i for i, d in self.devices.items() if "offline" in d.settings["faults"]}
            for publisher in self.connections:
                publisher.flush(offline)
            results = []
            for device, payload in sent:
                if payload is None:
                    status = "missing"
                elif any(p is payload for p in self.publishers[device.device_id].pending):
                    status = "queued"
                else:
                    status = "published"
                results.append({"device_id": device.device_id, "status": status, "payload": payload})
                LOG.info("manual reading device=%s status=%s", device.device_id, status)
            return results


def csp(page: bytes) -> str:
    # Hash-pin the page's inline script and style so nothing else can execute.
    hashes = {tag: " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(body).digest()).decode()}'" for body in re.findall(rb"<%s>(.*?)</%s>" % (tag, tag), page, re.S)) for tag in (b"script", b"style")}
    return f"default-src 'none'; script-src {hashes[b'script']}; style-src {hashes[b'style']}; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def make_handler(panel: Panel, allowed_hosts: set[str] | None = None):
    """allowed_hosts guards against DNS rebinding and cross-site writes; None disables the check."""
    page = UI_PATH.read_bytes()
    policy = csp(page)

    class Handler(BaseHTTPRequestHandler):
        timeout = 10  # Drop idle or slow clients instead of holding a worker thread.

        def log_message(self, fmt, *args):
            LOG.debug("http %s", fmt % args)

        def reply(self, status: int, body, content_type: str = "application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if content_type.startswith("text/html"):
                self.send_header("Content-Security-Policy", policy)
            self.end_headers()
            self.wfile.write(data)

        def trusted(self) -> bool:
            if allowed_hosts is None:
                return True
            host = urlsplit("//" + self.headers.get("Host", "")).hostname
            origin = self.headers.get("Origin")
            if host not in allowed_hosts or (origin is not None and urlsplit(origin).hostname not in allowed_hosts):
                self.reply(403, {"error": "untrusted host or origin"})
                return False
            return True

        def do_GET(self):
            if not self.trusted():
                return
            if self.path == "/":
                self.reply(200, page, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self.reply(200, panel.state())
            else:
                self.reply(404, {"error": "not found"})

        def do_POST(self):
            if not self.trusted():
                return
            # Requiring JSON forces a CORS preflight, so other sites cannot submit forms here.
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self.reply(415, {"error": "Content-Type must be application/json"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= MAX_BODY:
                    raise ValueError("Invalid request body length")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("Request body must be a JSON object")
                match = re.fullmatch(r"/api/devices/([a-zA-Z0-9_-]{1,64})", self.path)
                if match:
                    self.reply(200, panel.update(match.group(1), body))
                elif self.path == "/api/send":
                    ids = list(panel.devices) if body.get("all") else body.get("devices")
                    if not isinstance(ids, list) or not ids:
                        raise ValueError("Provide a non-empty devices list or all=true")
                    self.reply(200, {"results": panel.send(ids), "queued": panel.queued()})
                else:
                    self.reply(404, {"error": "not found"})
            except KeyError as error:
                self.reply(404, {"error": f"unknown device {error}"})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.reply(400, {"error": str(error)})

    return Handler


def serve(panel: Panel, host: str, port: int, stop: threading.Event, allowed_hosts: list[str] | None = None):
    trusted = set(allowed_hosts or []) | LOOPBACK | ({host} if host not in ("0.0.0.0", "::") else set())
    server = ThreadingHTTPServer((host, port), make_handler(panel, trusted))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    LOG.info("Manual panel listening on http://%s:%s", host, port)
    try:
        while not stop.wait(0.5):
            pass
    finally:
        server.shutdown()
        server.server_close()
