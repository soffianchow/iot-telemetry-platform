"""Real broker, real consumer process, no mocked network or database."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import paho.mqtt.client as mqtt
import pytest

from iot_ops.mqtt import BufferedPublisher, make_client, start
from iot_ops.simulator import VirtualDevice

pytestmark = pytest.mark.skipif(not os.getenv('MQTT_HOST'), reason='requires Compose broker; run make integration')


def test_real_mqtt_validation_dedup_and_recovery(tmp_path):
    db = tmp_path / 'integration.db'
    log_path = tmp_path / 'consumer.log'
    with log_path.open('w') as log:
        consumer = subprocess.Popen([sys.executable, '-m', 'iot_ops', 'consume', '--db', str(db), '--max-messages', '10'], stdout=log, stderr=log, env={**os.environ, 'MQTT_CLIENT_ID': 'integration-consumer'})
        client = make_client('integration-producer')
        ready = threading.Event()
        client.on_connect = lambda c, u, f, r, p: ready.set() if r == 0 else None
        start(client)
        try:
            assert ready.wait(10), 'producer failed to connect to broker'
            deadline = time.monotonic() + 10
            while 'Subscribed to telemetry' not in log_path.read_text():
                assert consumer.poll() is None, log_path.read_text()
                assert time.monotonic() < deadline, log_path.read_text()
                time.sleep(.05)
            topic = 'iot-ops/devices/integration-000/telemetry'
            client.publish(topic, '{broken', qos=1).wait_for_publish(5)
            for i in range(10):
                device_id = f'integration-{i:03d}'
                faults = [{'kind': 'pump_fault', 'start_cycle': 0, 'duration_cycles': 1}] if i == 0 else []
                payload = VirtualDevice({'device_id': device_id, 'faults': faults}, i).sample(0)
                target = f'iot-ops/devices/{device_id}/telemetry'
                if i == 0:
                    client.publish('iot-ops/devices/wrong-device/telemetry', json.dumps(payload), qos=1).wait_for_publish(5)
                # Send duplicate before final unique reading ends the bounded consumer.
                for _ in range(2 if i < 9 else 1):
                    client.publish(target, json.dumps(payload), qos=1).wait_for_publish(5)
            assert consumer.wait(timeout=20) == 0, log_path.read_text()
            with sqlite3.connect(db) as connection:
                assert connection.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0] == 10
                assert connection.execute('SELECT COUNT(*) FROM latest').fetchone()[0] == 10
                assert connection.execute("SELECT COUNT(*) FROM events WHERE kind='pump_fault'").fetchone()[0] == 1
            assert 'Rejected message' in log_path.read_text()
        finally:
            client.disconnect()
            client.loop_stop()
            if consumer.poll() is None:
                consumer.terminate()
                consumer.wait(timeout=5)


def test_bounded_buffer_flushes_over_real_broker():
    client = make_client('integration-buffer')
    publisher = BufferedPublisher(client, capacity=2)
    received = []
    subscriber = make_client('integration-observer')
    subscribed = threading.Event()
    subscriber.on_connect = lambda c, u, f, r, p: c.subscribe('iot-ops/devices/buffer-test/telemetry', qos=1)
    subscriber.on_subscribe = lambda *args: subscribed.set()
    subscriber.on_message = lambda c, u, m: received.append(json.loads(m.payload)['sequence'])
    start(subscriber)
    try:
        assert subscribed.wait(10)
        for cycle in range(3):
            publisher.enqueue(VirtualDevice({'device_id': 'buffer-test'}, start_sequence=cycle).sample(0))
        assert publisher.dropped == 1
        assert len(publisher.pending) == 2
        start(client)
        assert publisher.connected.wait(10)
        publisher.flush(timeout=5)
        deadline = time.monotonic() + 5
        while len(received) < 2 and time.monotonic() < deadline:
            time.sleep(.05)
        assert received == [1, 2]
        assert not publisher.pending
        # Actual transport disconnect / reconnect, then flush another buffered reading.
        client.disconnect()
        deadline = time.monotonic() + 5
        while publisher.connected.is_set() and time.monotonic() < deadline:
            time.sleep(.05)
        assert not publisher.connected.is_set()
        publisher.enqueue(VirtualDevice({'device_id': 'buffer-test'}, start_sequence=3).sample(0))
        client.loop_stop()
        client.reconnect()
        client.loop_start()
        assert publisher.connected.wait(10)
        publisher.flush(timeout=5)
        deadline = time.monotonic() + 5
        while len(received) < 3 and time.monotonic() < deadline:
            time.sleep(.05)
        assert received == [1, 2, 3]
    finally:
        client.disconnect()
        client.loop_stop()
        subscriber.disconnect()
        subscriber.loop_stop()
