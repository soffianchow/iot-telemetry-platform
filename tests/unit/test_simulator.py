from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from iot_ops.simulator import VirtualDevice, active_faults, load_config
from iot_ops.validation import validate


def test_ten_devices_and_all_schedules_validate():
    config = load_config('config/devices.json')
    assert len(config['devices']) == 10
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, cfg in enumerate(config['devices']):
        device = VirtualDevice(cfg, i)
        for cycle in range(150):
            sample = device.sample(cycle, now)
            if sample:
                validate(sample, f"iot-ops/devices/{cfg['device_id']}/telemetry")


def test_smooth_deterministic_timeseries():
    a, b = VirtualDevice({'device_id': 'a'}), VirtualDevice({'device_id': 'a'})
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    previous = None
    for cycle in range(100):
        first = a.sample(cycle, now)
        assert first == b.sample(cycle, now)
        if previous:
            assert abs(first['metrics']['temperature_c'] - previous['metrics']['temperature_c']) < 0.11
        previous = first


@pytest.mark.parametrize('kind', ['missing', 'offline', 'anomaly', 'sensor_failure', 'pump_fault'])
def test_faults_have_observable_behavior(kind):
    cfg = {'device_id': 'a', 'faults': [{'kind': kind, 'start_cycle': 1, 'duration_cycles': 1, 'repeat_every': 4}]}
    device = VirtualDevice(cfg)
    baseline = device.sample(0)
    faulty = device.sample(1)
    restored = device.sample(2)
    assert restored['sequence'] == 2
    assert restored['quality'] == []
    assert kind in active_faults(cfg, 5)
    if kind == 'missing':
        assert faulty is None
    else:
        assert kind in faulty['quality']
        validate(faulty)
        if kind == 'anomaly':
            assert faulty['metrics']['temperature_c'] > baseline['metrics']['temperature_c'] + 10
        elif kind == 'sensor_failure':
            assert faulty['metrics']['temperature_c'] is None
        elif kind == 'pump_fault':
            assert faulty['metrics']['pump_state'] == 'fault'
        elif kind == 'offline':
            assert faulty['connectivity'] == 'offline'


def test_duplicate_device_config_rejected(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps({'devices': [{'device_id': 'a'}, {'device_id': 'a'}]}))
    with pytest.raises(ValueError):
        load_config(str(path))


def test_schema_distribution_is_identical():
    assert json.loads(Path('schemas/telemetry.schema.json').read_text()) == json.loads(Path('src/iot_ops/telemetry.schema.json').read_text())
