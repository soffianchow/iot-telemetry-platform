"""Deterministic, stateful device models with reproducible fault schedules."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

FAULTS = {"anomaly", "offline", "sensor_failure", "missing", "pump_fault"}


def load_config(path: str) -> dict:
    config = json.loads(Path(path).read_text())
    devices = config.get("devices", [])
    ids = [d.get("device_id") for d in devices]
    if not devices or any(not isinstance(i, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", i) for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Configuration requires unique valid device IDs")
    for device in devices:
        for fault in device.get("faults", []):
            if fault.get("kind") not in FAULTS or not isinstance(fault.get("start_cycle"), int) or fault["start_cycle"] < 0 or not isinstance(fault.get("duration_cycles"), int) or fault["duration_cycles"] <= 0:
                raise ValueError("Invalid fault schedule")
            if "repeat_every" in fault and (not isinstance(fault["repeat_every"], int) or fault["repeat_every"] < fault["duration_cycles"]):
                raise ValueError("Fault repeat must be at least its duration")
    return config


def active_faults(config: dict, cycle: int) -> set[str]:
    active = set()
    for fault in config.get("faults", []):
        offset = cycle - fault["start_cycle"]
        if offset < 0:
            continue
        if fault.get("repeat_every"):
            offset %= fault["repeat_every"]
        if offset < fault["duration_cycles"]:
            active.add(fault["kind"])
    return active


class VirtualDevice:
    def __init__(self, config: dict, index: int = 0, start_sequence: int = 0):
        self.config = config
        self.index = index
        self.sequence = start_sequence
        self.soil = 48.0 + index
        self.tank = 90.0
        self.battery = 100.0

    def sample(self, cycle: int, now: datetime | None = None) -> dict | None:
        faults = active_faults(self.config, cycle)
        sequence = self.sequence
        self.sequence += 1  # Gaps are observable even when a message is missing.
        phase = cycle / 40 + self.index * 0.3
        pump = self.soil < 44 or cycle % 60 in (0, 1, 2)
        if "pump_fault" in faults:
            pump_state = "fault"
        else:
            pump_state = "on" if pump else "off"
        self.soil = max(0, min(100, self.soil + (1.0 if pump_state == "on" else -0.12)))
        self.tank = max(0, self.tank - (0.15 if pump_state == "on" else 0.002))
        self.battery = max(0, self.battery - (0.003 if pump_state == "on" else 0.001))
        if "missing" in faults:
            return None
        metrics = {
            "temperature_c": None if "sensor_failure" in faults else round(24 + 4 * math.sin(phase) + (14 if "anomaly" in faults else 0), 2),
            "humidity_pct": round(65 - 12 * math.sin(phase) + math.sin(phase * 3), 2),
            "soil_moisture_pct": round(self.soil, 2),
            "light_lux": round(max(0, 35000 * (0.5 + 0.5 * math.sin(phase - 1))), 1),
            "tank_level_pct": round(self.tank, 2), "pump_state": pump_state,
            "battery_pct": round(self.battery, 3),
        }
        return {
            "schema_version": 1, "device_id": self.config["device_id"],
            "timestamp": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sequence": sequence, "signal_strength_dbm": round(-62 + 8 * math.sin(phase / 3) - (35 if "offline" in faults else 0), 1),
            "connectivity": "offline" if "offline" in faults else "online",
            "metrics": metrics, "quality": sorted(faults - {"missing"}),
        }
