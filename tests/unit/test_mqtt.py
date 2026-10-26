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
