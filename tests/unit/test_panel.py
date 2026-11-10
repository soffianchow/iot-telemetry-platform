from itertools import combinations
import http.client
import json
import threading
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import paho.mqtt.client as mqtt
import pytest
from iot_ops.mqtt import BufferedPublisher
from iot_ops.panel import CROPS, FAULTS, ManualDevice, Panel, make_handler
from iot_ops.validation import validate
from http.server import ThreadingHTTPServer


def panel(connected=True):
    client = Mock()
    info = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    info.is_published.return_value = True
    client.publish.return_value = info
    publisher = BufferedPublisher(client, 10)
    if connected:
        publisher.connected.set()
    return Panel([ManualDevice("plot-01", "lettuce"), ManualDevice("plot-02", "tomato")], publisher), client


def test_crop_presets_sensors_to_target_midpoint():
    device = ManualDevice("plot-01", "tomato")
    assert device.settings["temperature_c"] == 24
    device.update({"crop": "lettuce", "humidity_pct": 90})
    assert device.crop == "lettuce" and device.settings["temperature_c"] == 20 and device.settings["humidity_pct"] == 90


@pytest.mark.parametrize("faults", [list(c) for n in range(len(FAULTS) + 1) for c in combinations(FAULTS, n)])
def test_every_fault_combination_is_schema_valid(faults):
    device = ManualDevice("plot-01", "chili")
    device.update({"faults": faults, "temperature_c": 95, "signal_strength_dbm": -110})
    payload = device.reading()
    if "missing" in faults:
        assert payload is None and device.sequence == 1
    else:
        validate(payload, "iot-ops/devices/plot-01/telemetry")


@pytest.mark.parametrize("crop", CROPS)
def test_auto_pump_waters_until_crop_minimum(crop):
    device = ManualDevice("plot-01", crop)
    low = CROPS[crop]["soil_moisture_pct"][0]
    device.update({"soil_moisture_pct": low - 3})
    states = [device.reading()["metrics"]["pump_state"] for _ in range(3)]
    assert states == ["on", "on", "off"]
    assert device.settings["tank_level_pct"] == 88


def test_empty_tank_stops_pump_and_manual_modes_override_auto():
    device = ManualDevice("plot-01")
    device.update({"pump_mode": "on", "tank_level_pct": 0})
    assert device.pump_state() == "off"
    device.update({"tank_level_pct": 50, "pump_mode": "off", "soil_moisture_pct": 0})
    assert device.pump_state() == "off"


@pytest.mark.parametrize("changes", [
    {"temperature_c": 101}, {"humidity_pct": "50"}, {"light_lux": True}, {"crop": "rice"},
    {"pump_mode": "turbo"}, {"faults": ["meteor"]}, {"faults": "anomaly"}, {"colour": "red"},
])
def test_invalid_changes_rejected_without_partial_update(changes):
    device = ManualDevice("plot-01")
    before = json.dumps(device.settings, sort_keys=True)
    with pytest.raises(ValueError):
        device.update({"humidity_pct": 10, **changes})
    assert json.dumps(device.settings, sort_keys=True) == before


def test_send_publishes_only_requested_devices_once():
    p, client = panel()
    results = p.send(["plot-02"])
    assert [r["status"] for r in results] == ["published"]
    client.publish.assert_called_once()
    assert client.publish.call_args.args[0] == "iot-ops/devices/plot-02/telemetry"


def test_offline_device_queues_until_it_reconnects():
    p, client = panel()
    p.update("plot-01", {"faults": ["offline"]})
    assert p.send(["plot-01"])[0]["status"] == "queued"
    client.publish.assert_not_called()
    p.update("plot-01", {"faults": []})
    assert p.send(["plot-01"])[0]["status"] == "published"
    assert client.publish.call_count == 2


def test_broker_down_queues_and_missing_reports_skip():
    p, client = panel(connected=False)
    p.update("plot-02", {"faults": ["missing"]})
    statuses = {r["device_id"]: r["status"] for r in p.send(["plot-01", "plot-02"])}
    assert statuses == {"plot-01": "queued", "plot-02": "missing"}
    with pytest.raises(KeyError):
        p.send(["plot-99"])


@pytest.fixture
def server():
    p, client = panel()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(p, {"127.0.0.1"}))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", client
    httpd.shutdown()
    httpd.server_close()


def call(url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    with urlopen(Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})}), timeout=5) as response:
        return response.status, response.read()


def test_http_ui_state_update_and_send(server):
    base, client = server
    status, page = call(base + "/")
    assert status == 200 and b"Sensor Panel" in page
    state = json.loads(call(base + "/api/state")[1])
    assert [d["device_id"] for d in state["devices"]] == ["plot-01", "plot-02"]
    client.publish.assert_not_called()  # Reading state never publishes.
    view = json.loads(call(base + "/api/devices/plot-01", {"crop": "chili"})[1])
    assert view["crop"] == "chili"
    sent = json.loads(call(base + "/api/send", {"all": True})[1])
    assert [r["status"] for r in sent["results"]] == ["published", "published"]


@pytest.mark.parametrize("path,body,code", [
    ("/api/devices/plot-01", {"temperature_c": 500}, 400),
    ("/api/devices/plot-99", {"crop": "chili"}, 404),
    ("/api/send", {"devices": []}, 400),
    ("/api/send", {"devices": ["plot-99"]}, 404),
    ("/api/nope", {}, 404),
    ("/api/devices/plot-01", {"faults": [{}]}, 400),
    ("/api/devices/plot-01", {"crop": []}, 400),
    ("/api/devices/plot-01", {"pump_mode": ["on"]}, 400),
    ("/api/send", {"devices": [["plot-01"]]}, 400),
])
def test_http_errors(server, path, body, code):
    with pytest.raises(HTTPError) as error:
        call(server[0] + path, body)
    assert error.value.code == code


@pytest.mark.parametrize("headers,code", [
    ({"Content-Type": "application/x-www-form-urlencoded"}, 415),
    ({"Content-Type": "text/plain"}, 415),
    ({"Host": "attacker.example"}, 403),
    ({"Origin": "http://attacker.example"}, 403),
])
def test_cross_site_and_rebinding_requests_rejected(server, headers, code):
    base, client = server
    with pytest.raises(HTTPError) as error:
        call(base + "/api/send", {"all": True}, headers)
    assert error.value.code == code
    client.publish.assert_not_called()


def test_same_origin_post_allowed(server):
    base, _ = server
    assert call(base + "/api/send", {"all": True}, {"Origin": base})[0] == 200


def test_negative_content_length_rejected(server):
    host, port = server[0].removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.putrequest("POST", "/api/send")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "-1")
    conn.endheaders()
    assert conn.getresponse().status == 400


def test_ui_served_with_hash_pinned_csp(server):
    with urlopen(server[0] + "/", timeout=5) as response:
        policy = response.headers["Content-Security-Policy"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'sha256-" in policy and "unsafe-inline" not in policy and "frame-ancestors 'none'" in policy


def test_reading_reports_operator_value_then_waters_for_next_step():
    device = ManualDevice("plot-01", "lettuce")
    device.update({"soil_moisture_pct": 40})
    first = device.reading()["metrics"]
    assert (first["soil_moisture_pct"], first["pump_state"], first["tank_level_pct"]) == (40, "on", 90)
    second = device.reading()["metrics"]
    assert (second["soil_moisture_pct"], second["tank_level_pct"]) == (42, 89)


def test_per_device_connections_publish_independently():
    clients, publishers = {}, {}
    for device_id in ("plot-01", "plot-02"):
        client = Mock()
        info = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
        info.is_published.return_value = True
        client.publish.return_value = info
        clients[device_id], publishers[device_id] = client, BufferedPublisher(client, 10)
    publishers["plot-01"].connected.set()
    p = Panel([ManualDevice("plot-01"), ManualDevice("plot-02")], publishers)
    assert len(p.connections) == 2 and p.state()["broker_connected"] is False
    statuses = {r["device_id"]: r["status"] for r in p.send(["plot-01", "plot-02"])}
    assert statuses == {"plot-01": "published", "plot-02": "queued"}
    assert clients["plot-01"].publish.call_args.args[0] == "iot-ops/devices/plot-01/telemetry"
    clients["plot-02"].publish.assert_not_called()
