"""QoS 1 transport: bounded volatile queues and reconnecting clients."""
from collections import deque
import json
import logging
import os
from pathlib import Path
import ssl
import threading
import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)


def tls_identity(device_id: str | None = None) -> tuple[str, str | None, str | None] | None:
    """Return (ca, cert, key) when MQTT_TLS_CA is set; MQTT_CERT_DIR selects a per-device identity."""
    ca, cert_dir = os.getenv("MQTT_TLS_CA"), os.getenv("MQTT_CERT_DIR")
    cert, key = os.getenv("MQTT_TLS_CERT"), os.getenv("MQTT_TLS_KEY")
    # Partial TLS settings must fail loudly rather than fall back to plaintext.
    if not ca:
        if cert or key or cert_dir:
            raise ValueError("MQTT_TLS_CA is required when client certificates are configured")
        return None
    if bool(cert) != bool(key):
        raise ValueError("MQTT_TLS_CERT and MQTT_TLS_KEY must be set together")
    if cert_dir and not device_id and not cert:
        raise ValueError("MQTT_CERT_DIR requires a device ID or a shared certificate pair")
    if device_id and cert_dir:
        return ca, str(Path(cert_dir) / f"{device_id}.cert.pem"), str(Path(cert_dir) / f"{device_id}.key.pem")
    return ca, cert, key


def make_client(client_id: str, *, manual_ack: bool = False, tls: tuple[str, str | None, str | None] | None = None) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, manual_ack=manual_ack, clean_session=not manual_ack)
    if tls:
        ca, cert, key = tls
        # Verified server certificate and hostname, TLS 1.2+, optional client certificate (mutual TLS).
        context = ssl.create_default_context(cafile=ca)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if cert:
            context.load_cert_chain(cert, key)
        client.tls_set_context(context)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.max_inflight_messages_set(1)
    client.max_queued_messages_set(1)
    if os.getenv("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.getenv("MQTT_PASSWORD"))
    return client


def start(client: mqtt.Client):
    default_port = "8883" if os.getenv("MQTT_TLS_CA") else "1883"
    client.connect_async(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", default_port)), keepalive=30)
    client.loop_start()


class BufferedPublisher:
    def __init__(self, client: mqtt.Client, capacity: int = 1000):
        if capacity <= 0:
            raise ValueError("Buffer capacity must be positive")
        self.client = client
        self.pending = deque()
        self.capacity = capacity
        self.dropped = 0
        self.connected = threading.Event()
        client.on_connect = self._connect
        client.on_disconnect = self._disconnect

    def _connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.connected.set()
            LOG.info("MQTT connected")
        else:
            LOG.error("MQTT connection rejected: %s", reason_code)

    def _disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()
        LOG.warning("MQTT disconnected; buffering (reason=%s)", reason_code)

    def enqueue(self, payload: dict):
        if len(self.pending) >= self.capacity:
            self.pending.popleft()
            self.dropped += 1
            LOG.warning("Offline buffer full; oldest message dropped total=%s", self.dropped)
        self.pending.append(payload)

    def flush(self, unavailable_devices: set[str] | None = None, timeout: float = 0.5):
        # Rotate unavailable assets so one simulated outage cannot block other devices.
        for _ in range(len(self.pending)):
            if not self.connected.is_set():
                break
            payload = self.pending[0]
            if payload["device_id"] in (unavailable_devices or set()):
                self.pending.rotate(-1)
                continue
            try:
                info = self.client.publish(f"iot-ops/devices/{payload['device_id']}/telemetry", json.dumps(payload), qos=1)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    LOG.warning("Publish deferred rc=%s", info.rc)
                    break
                info.wait_for_publish(timeout=timeout)
                if not info.is_published():
                    break
            except (RuntimeError, ValueError, OSError) as error:
                LOG.warning("Publish deferred: %s", error)
                break
            self.pending.popleft()
