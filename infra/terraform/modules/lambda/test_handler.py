"""AWS-free tests for trust boundary, deduplication and storage semantics."""
import importlib.util
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("cloud_handler", Path(__file__).with_name("handler.py"))
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


class Table:
    def __init__(self):
        self.calls = []
        self.error = None

    def put_item(self, **kwargs):
        if self.error:
            raise self.error
        self.calls.append(kwargs)


@pytest.fixture
def setup(monkeypatch):
    table = Table()
    monkeypatch.setattr(cloud, "_TABLE", table)
    monkeypatch.setenv("DEVICE_IDS", "device-001")
    monkeypatch.setenv("RETENTION_DAYS", "7")
    event = {
        "schema_version": 1, "device_id": "device-001", "source_device_id": "device-001",
        "timestamp": "2026-01-01T00:00:00Z", "sequence": 12, "signal_strength_dbm": -60,
        "connectivity": "online", "quality": [], "metrics": {
            "temperature_c": 26.5, "humidity_pct": 65, "soil_moisture_pct": 45,
            "light_lux": 1000, "tank_level_pct": 80, "pump_state": "off", "battery_pct": 99,
        },
    }
    return table, event


def test_valid_event_uses_decimal_ttl_and_conditional_write(setup):
    table, event = setup
    assert cloud.handler(event, None) == {"status": "stored"}
    call = table.calls[0]
    item = call["Item"]
    assert item["metrics"]["temperature_c"] == Decimal("26.5")
    assert item["expires_at"] == int(datetime.fromisoformat("2026-01-08T00:00:00+00:00").timestamp())
    assert item["event_key"] == "2026-01-01T00:00:00+00:00#00000000000000000012"
    assert "source_device_id" not in item
    assert "ConditionExpression" in call
    assert "source_device_id" in event  # Caller payload remains untouched.


@pytest.mark.parametrize("change", [
    {"source_device_id": "device-002"}, {"device_id": "unregistered", "source_device_id": "unregistered"},
    {"sequence": -1}, {"unexpected": True}, {"timestamp": "not-a-date"},
])
def test_invalid_or_untrusted_event_rejected_before_aws(setup, change):
    table, event = setup
    event.update(change)
    with pytest.raises(Exception):
        cloud.handler(event, None)
    assert not table.calls


def test_duplicate_is_success(setup):
    table, event = setup
    class Duplicate(Exception):
        response = {"Error": {"Code": "ConditionalCheckFailedException"}}
    table.error = Duplicate()
    assert cloud.handler(event, None) == {"status": "duplicate"}


def test_storage_failure_propagates_for_retry(setup):
    table, event = setup
    table.error = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        cloud.handler(event, None)
