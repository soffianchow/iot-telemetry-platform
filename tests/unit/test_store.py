from copy import deepcopy
import pytest
from jsonschema import ValidationError
from iot_ops.simulator import VirtualDevice
from iot_ops.store import TelemetryStore
from iot_ops.validation import validate


def test_dedup_retention_gap_and_latest(tmp_path):
    store = TelemetryStore(str(tmp_path / 'data.db'), max_rows=2)
    device = VirtualDevice({'device_id': 'a'})
    first = device.sample(0)
    assert store.process(first)
    assert not store.process(first)
    device.sample(1)
    assert store.process(device.sample(2))
    assert store.process(device.sample(3))
    assert not store.process(first)  # Even when aged out of history.
    result = store.status()
    assert result['stored_messages'] == 2
    assert result['devices'][0]['sequence'] == 3
    assert any(event['kind'] == 'sequence_gap' for event in result['recent_events'])
    store.close()


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(timestamp='nonsense'),
    lambda p: p.update(sequence=-1),
    lambda p: p.update(sequence=2**63),
    lambda p: p.update(surprise=True),
    lambda p: p['metrics'].update(humidity_pct=101),
    lambda p: p['metrics'].update(temperature_c=None),
    lambda p: p['metrics'].update(pump_state='fault'),
    lambda p: p.update(connectivity='offline'),
])
def test_invalid_payloads_rejected(mutation):
    payload = VirtualDevice({'device_id': 'a'}).sample(0)
    mutation(payload)
    with pytest.raises((ValueError, ValidationError)):
        validate(payload)


def test_topic_identity_rejected():
    payload = VirtualDevice({'device_id': 'a'}).sample(0)
    with pytest.raises(ValueError):
        validate(payload, 'iot-ops/devices/b/telemetry')


def test_out_of_order_does_not_regress_latest(tmp_path):
    store = TelemetryStore(str(tmp_path / 'db'))
    device = VirtualDevice({'device_id': 'a'})
    older, newer = device.sample(0), device.sample(1)
    assert store.process(newer)
    assert not store.process(older)
    assert store.status()['devices'][0]['sequence'] == 1
    store.close()


def test_rejected_payload_never_written(tmp_path):
    store = TelemetryStore(str(tmp_path / 'db'))
    bad = VirtualDevice({'device_id': 'a'}).sample(0)
    bad['sequence'] = -1
    with pytest.raises(ValidationError):
        store.process(bad)
    assert store.status()['stored_messages'] == 0
    store.close()
