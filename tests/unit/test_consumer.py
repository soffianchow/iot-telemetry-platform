"""Exercise CLI callbacks, including storage failure acknowledgement boundaries."""
import json
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from iot_ops import __main__ as cli
from iot_ops.simulator import VirtualDevice


def run_consumer(monkeypatch, tmp_path, messages, *, fail_storage=False):
    monkeypatch.setattr(sys, 'argv', ['iot-ops', 'consume', '--db', str(tmp_path / 'db'), '--max-messages', '1'])
    client = Mock()
    monkeypatch.setattr(cli, 'make_client', lambda *a, **k: client)
    if fail_storage:
        monkeypatch.setattr(cli, 'TelemetryStore', Mock(side_effect=sqlite3.OperationalError('disk full')))
    def start(c):
        c.on_connect(c, None, None, 0, None)
        for mid, payload in enumerate(messages, 1):
            c.on_message(c, None, SimpleNamespace(payload=payload, topic='iot-ops/devices/a/telemetry', qos=1, mid=mid))
    monkeypatch.setattr(cli, 'start', start)
    if fail_storage:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
    else:
        cli.main()
    return client


def test_poison_message_acked_and_consumer_keeps_processing(monkeypatch, tmp_path):
    payload = json.dumps(VirtualDevice({'device_id': 'a'}).sample(0)).encode()
    client = run_consumer(monkeypatch, tmp_path, [b'invalid-json', payload])
    assert client.ack.call_count == 2
    client.subscribe.assert_called_once_with('iot-ops/devices/+/telemetry', qos=1)


def test_storage_failure_not_acked_and_exits_nonzero(monkeypatch, tmp_path):
    payload = json.dumps(VirtualDevice({'device_id': 'a'}).sample(0)).encode()
    client = run_consumer(monkeypatch, tmp_path, [payload], fail_storage=True)
    client.ack.assert_not_called()
