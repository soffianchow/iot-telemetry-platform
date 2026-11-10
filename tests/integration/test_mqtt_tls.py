"""Real mutual-TLS transport and per-device topic isolation against Mosquitto."""
import json
import os
import socket
import ssl
from pathlib import Path
import threading
import time

import pytest

from iot_ops.mqtt import BufferedPublisher, make_client, start, tls_identity
from iot_ops.panel import ManualDevice, Panel

pytestmark = pytest.mark.skipif(not os.getenv('MQTT_TLS_TEST_DIR'), reason='requires TLS broker; run scripts/test-tls.sh')
CERTS = Path(os.getenv('MQTT_TLS_TEST_DIR', '.'))


@pytest.fixture
def tls_env(monkeypatch):
    for name in ('MQTT_TLS_CERT', 'MQTT_TLS_KEY', 'MQTT_USERNAME', 'MQTT_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('MQTT_TLS_CA', str(CERTS / 'ca.pem'))
    monkeypatch.setenv('MQTT_CERT_DIR', str(CERTS))


def connect(client_id, timeout=10):
    client = make_client(client_id, tls=tls_identity(client_id))
    result = {}
    ready = threading.Event()
    def on_connect(c, userdata, flags, reason_code, properties):
        result['rc'] = reason_code
        ready.set()
    client.on_connect = on_connect
    start(client)
    ready.wait(timeout)
    return client, result.get('rc')


@pytest.fixture
def observer(tls_env):
    client, rc = connect('observer')
    assert rc == 0
    received = []
    subscribed = threading.Event()
    client.on_message = lambda c, u, msg: received.append((msg.topic, json.loads(msg.payload)))
    client.on_subscribe = lambda *a: subscribed.set()
    client.subscribe('iot-ops/devices/+/telemetry', qos=1)
    assert subscribed.wait(5)
    yield received
    client.disconnect()
    client.loop_stop()


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_device_publishes_only_on_its_own_topic(observer):
    client, rc = connect('plot-01')
    assert rc == 0
    try:
        own = ManualDevice('plot-01').reading()
        client.publish('iot-ops/devices/plot-01/telemetry', json.dumps(own), qos=1).wait_for_publish(5)
        spoof = {**ManualDevice('plot-02').reading()}
        client.publish('iot-ops/devices/plot-02/telemetry', json.dumps(spoof), qos=1).wait_for_publish(5)
        assert wait_for(lambda: any(t.endswith('plot-01/telemetry') for t, _ in observer))
        time.sleep(1)
        assert [t for t, _ in observer] == ['iot-ops/devices/plot-01/telemetry'], 'ACL must drop impersonation'
    finally:
        client.disconnect()
        client.loop_stop()


def test_connection_without_client_certificate_is_rejected(monkeypatch, tls_env):
    # Prove the broker is reachable first, so the rejection below is about the missing certificate.
    control, rc = connect('plot-01')
    control.disconnect()
    control.loop_stop()
    assert rc == 0
    monkeypatch.delenv('MQTT_CERT_DIR')
    client = make_client('anonymous', tls=tls_identity())
    connected = threading.Event()
    client.on_connect = lambda c, u, f, rc, p: connected.set() if rc == 0 else None
    start(client)
    try:
        assert not connected.wait(3)
    finally:
        client.disconnect()
        client.loop_stop()


def test_claimed_client_id_cannot_override_certificate_identity(observer):
    # plot-01's certificate asking to be client "plot-02" is still treated as plot-01.
    client = make_client('plot-02', tls=tls_identity('plot-01'))
    ready = threading.Event()
    client.on_connect = lambda c, u, f, rc, p: ready.set() if rc == 0 else None
    start(client)
    try:
        assert ready.wait(10)
        client.publish('iot-ops/devices/plot-02/telemetry', json.dumps(ManualDevice('plot-02').reading()), qos=1).wait_for_publish(5)
        time.sleep(1)
        assert observer == []
    finally:
        client.disconnect()
        client.loop_stop()


def test_panel_sends_each_plot_with_its_own_identity(observer):
    devices = [ManualDevice('plot-01', 'lettuce'), ManualDevice('plot-02', 'tomato')]
    publishers = {d.device_id: BufferedPublisher(make_client(d.device_id, tls=tls_identity(d.device_id))) for d in devices}
    panel = Panel(devices, publishers)
    for publisher in panel.connections:
        start(publisher.client)
    try:
        assert wait_for(lambda: panel.state()['broker_connected'], 10)
        results = panel.send(['plot-01', 'plot-02'])
        assert [r['status'] for r in results] == ['published', 'published']
        assert wait_for(lambda: len(observer) == 2)
        assert sorted(p['device_id'] for _, p in observer) == ['plot-01', 'plot-02']
    finally:
        for publisher in panel.connections:
            publisher.client.disconnect()
            publisher.client.loop_stop()


@pytest.mark.parametrize('failure', ['untrusted_ca', 'wrong_hostname'])
def test_server_certificate_verification_rejects_invalid_identity(tls_env, monkeypatch, failure):
    # Positive control distinguishes certificate rejection from an unavailable broker.
    control, rc = connect('plot-01')
    control.disconnect()
    control.loop_stop()
    assert rc == 0
    ca = CERTS / ('untrusted-ca.pem' if failure == 'untrusted_ca' else 'ca.pem')
    client = make_client('plot-01', tls=(str(ca), str(CERTS / 'plot-01.cert.pem'), str(CERTS / 'plot-01.key.pem')))
    host = os.environ['MQTT_HOST']
    if failure == 'wrong_hostname':
        # Resolve the deliberate wrong name locally; TLS must still verify that name.
        real_getaddrinfo = socket.getaddrinfo
        monkeypatch.setattr(socket, 'getaddrinfo', lambda h, p, *a, **kw: real_getaddrinfo(host, p, *a, **kw))
        host_to_verify = 'wrong-broker.invalid'
    else:
        host_to_verify = host
    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            client.connect(host_to_verify, int(os.environ['MQTT_PORT']))
    finally:
        client.disconnect()
