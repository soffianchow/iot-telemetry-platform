from unittest.mock import Mock
import paho.mqtt.client as mqtt
import pytest
from iot_ops.mqtt import BufferedPublisher
from iot_ops.simulator import VirtualDevice


def publisher(capacity=2):
    client = Mock()
    info = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    info.is_published.return_value = True
    client.publish.return_value = info
    return BufferedPublisher(client, capacity), client


def test_disconnected_queue_bounded_oldest_dropped():
    pub, client = publisher()
    d = VirtualDevice({'device_id': 'a'})
    for i in range(3):
        pub.enqueue(d.sample(i))
    pub.flush()
    assert len(pub.pending) == 2
    assert pub.pending[0]['sequence'] == 1
    assert pub.dropped == 1
    client.publish.assert_not_called()


def test_reconnect_drains_qos_one_after_ack():
    pub, client = publisher()
    pub.enqueue(VirtualDevice({'device_id': 'a'}).sample(0))
    pub._connect(None, None, None, 0, None)
    pub.flush()
    assert len(pub.pending) == 0
    assert client.publish.call_args.kwargs['qos'] == 1
    pub._disconnect(None, None, None, 1, None)
    assert not pub.connected.is_set()


@pytest.mark.parametrize('failure', ['error', 'timeout', 'exception'])
def test_publish_failure_preserves_pending(failure):
    pub, client = publisher()
    pub.connected.set()
    pub.enqueue(VirtualDevice({'device_id': 'a'}).sample(0))
    if failure == 'error':
        client.publish.return_value.rc = mqtt.MQTT_ERR_NO_CONN
    elif failure == 'timeout':
        client.publish.return_value.is_published.return_value = False
    else:
        client.publish.side_effect = OSError('connection lost')
    pub.flush()
    assert len(pub.pending) == 1


def test_simulated_offline_device_does_not_block_other_assets():
    pub, client = publisher(10)
    pub.connected.set()
    pub.enqueue(VirtualDevice({'device_id': 'a'}).sample(0))
    pub.enqueue(VirtualDevice({'device_id': 'b'}).sample(0))
    pub.flush({'a'})
    assert [p['device_id'] for p in pub.pending] == ['a']
    assert client.publish.call_count == 1
    pub.flush()
    assert not pub.pending


def test_tls_identity_selects_per_device_certificate(monkeypatch):
    from iot_ops.mqtt import tls_identity
    monkeypatch.delenv('MQTT_TLS_CA', raising=False)
    assert tls_identity('plot-01') is None
    monkeypatch.setenv('MQTT_TLS_CA', '/certs/ca.pem')
    monkeypatch.setenv('MQTT_TLS_CERT', '/certs/shared.pem')
    monkeypatch.setenv('MQTT_TLS_KEY', '/certs/shared.key')
    assert tls_identity() == ('/certs/ca.pem', '/certs/shared.pem', '/certs/shared.key')
    monkeypatch.setenv('MQTT_CERT_DIR', '/certs/devices')
    assert tls_identity('plot-01') == ('/certs/ca.pem', '/certs/devices/plot-01.cert.pem', '/certs/devices/plot-01.key.pem')


def test_tls_client_requires_verified_tls12(monkeypatch):
    import ssl
    from iot_ops.mqtt import make_client
    contexts = []
    real = ssl.create_default_context
    def capture(**kwargs):
        context = real()
        contexts.append((kwargs, context))
        return context
    monkeypatch.setattr(ssl, 'create_default_context', capture)
    make_client('plot-01', tls=('/certs/ca.pem', None, None))
    (kwargs, context), = contexts
    assert kwargs == {'cafile': '/certs/ca.pem'}
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_default_port_follows_tls(monkeypatch):
    from iot_ops.mqtt import start
    client = Mock()
    monkeypatch.delenv('MQTT_PORT', raising=False)
    monkeypatch.setenv('MQTT_TLS_CA', '/certs/ca.pem')
    start(client)
    assert client.connect_async.call_args.args[1] == 8883


@pytest.mark.parametrize('env', [
    {'MQTT_TLS_CERT': '/c.pem', 'MQTT_TLS_KEY': '/k.pem'},
    {'MQTT_CERT_DIR': '/certs'},
    {'MQTT_TLS_CA': '/ca.pem', 'MQTT_TLS_CERT': '/c.pem'},
    {'MQTT_TLS_CA': '/ca.pem', 'MQTT_TLS_KEY': '/k.pem'},
])
def test_partial_tls_settings_fail_instead_of_plaintext(monkeypatch, env):
    from iot_ops.mqtt import tls_identity
    for name in ('MQTT_TLS_CA', 'MQTT_TLS_CERT', 'MQTT_TLS_KEY', 'MQTT_CERT_DIR'):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        tls_identity('plot-01')


def test_certificate_directory_requires_device_id(monkeypatch):
    from iot_ops.mqtt import tls_identity
    for name in ('MQTT_TLS_CERT', 'MQTT_TLS_KEY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('MQTT_TLS_CA', '/certs/ca.pem')
    monkeypatch.setenv('MQTT_CERT_DIR', '/certs/devices')
    with pytest.raises(ValueError, match='device ID'):
        tls_identity()
