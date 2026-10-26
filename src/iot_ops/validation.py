"""Strict wire validation shared by local and cloud handlers."""
import json
from datetime import datetime
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).with_name("telemetry.schema.json")
_VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()), format_checker=FormatChecker())


def validate(payload: dict, topic: str | None = None) -> None:
    _VALIDATOR.validate(payload)
    json.dumps(payload, allow_nan=False)
    timestamp = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    if topic is not None and topic != f"iot-ops/devices/{payload['device_id']}/telemetry":
        raise ValueError("MQTT topic device does not match payload")
    quality, metrics = payload["quality"], payload["metrics"]
    if (metrics["temperature_c"] is None) != ("sensor_failure" in quality):
        raise ValueError("Null temperature requires sensor_failure quality")
    if (metrics["pump_state"] == "fault") != ("pump_fault" in quality):
        raise ValueError("Pump fault state and quality must agree")
    if (payload["connectivity"] == "offline") != ("offline" in quality):
        raise ValueError("Offline connectivity and quality must agree")
