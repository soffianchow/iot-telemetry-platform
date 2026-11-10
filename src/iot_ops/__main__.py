"""Operator CLI for local simulation and telemetry consumption."""
import argparse
import json
import logging
import os
import signal
import sqlite3
from jsonschema import ValidationError
import threading
import time
import paho.mqtt.client as mqtt
from .mqtt import BufferedPublisher, make_client, start, tls_identity
from .panel import ManualDevice, Panel, serve
from .simulator import VirtualDevice, active_faults, load_config
from .store import TelemetryStore

LOG = logging.getLogger(__name__)


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sim = commands.add_parser("simulate")
    sim.add_argument("--config", default="config/devices.json")
    sim.add_argument("--interval", type=float, default=2.0)
    sim.add_argument("--cycles", type=positive)
    sim.add_argument("--buffer-size", type=positive, default=1000)
    consumer = commands.add_parser("consume")
    consumer.add_argument("--db", default="data/telemetry.db")
    consumer.add_argument("--max-messages", type=positive)
    consumer.add_argument("--max-rows", type=positive, default=10000)
    panel = commands.add_parser("panel", help="Manual sensor panel; publishes only on request")
    panel.add_argument("--config", default="config/panel-devices.json")
    panel.add_argument("--host", default="127.0.0.1")
    panel.add_argument("--port", type=positive, default=8088)
    panel.add_argument("--buffer-size", type=positive, default=1000)
    panel.add_argument("--allowed-host", action="append", default=[], help="Extra hostname the UI may be reached by (e.g. a DNS name)")
    status = commands.add_parser("status")
    status.add_argument("--db", default="data/telemetry.db")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "status":
        store = TelemetryStore(args.db)
        print(json.dumps(store.status(), indent=2))
        store.close()
        return
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if args.command == "panel":
        config = load_config(args.config)
        seed = time.time_ns() // 1000
        devices = [ManualDevice(d["device_id"], d.get("crop", "lettuce"), seed) for d in config["devices"]]
        if os.getenv("MQTT_CERT_DIR"):
            # Per-device certificates: each plot connects as itself, so the broker can bind identity to topic.
            publishers = {d.device_id: BufferedPublisher(make_client(d.device_id, tls=tls_identity(d.device_id)), args.buffer_size) for d in devices}
        else:
            shared = BufferedPublisher(make_client(f"panel-{os.getpid()}", tls=tls_identity()), args.buffer_size)
            publishers = {d.device_id: shared for d in devices}
        panel = Panel(devices, publishers)
        for publisher in panel.connections:
            start(publisher.client)
        try:
            serve(panel, args.host, args.port, stop, args.allowed_host)
        finally:
            for publisher in panel.connections:
                publisher.flush(timeout=1)
                publisher.client.disconnect()
                publisher.client.loop_stop()
            LOG.info("Panel stopped queued=%s (queue is volatile)", panel.queued())
        return
    if args.command == "simulate":
        if args.interval <= 0:
            parser.error("--interval must be positive")
        config = load_config(args.config)
        # Microsecond wall-clock seed avoids sequence reuse across normal restarts.
        seed = time.time_ns() // 1000
        devices = [VirtualDevice(d, i, seed) for i, d in enumerate(config["devices"])]
        client = make_client(f"simulator-{os.getpid()}", tls=tls_identity())
        publisher = BufferedPublisher(client, args.buffer_size)
        start(client)
        cycle = 0
        try:
            while not stop.is_set() and (args.cycles is None or cycle < args.cycles):
                unavailable = {d.config["device_id"] for d in devices if "offline" in active_faults(d.config, cycle)}
                for device in devices:
                    payload = device.sample(cycle)
                    if payload:
                        publisher.enqueue(payload)
                publisher.flush(unavailable)
                LOG.info("cycle=%s devices=%s queued=%s dropped=%s", cycle, len(devices), len(publisher.pending), publisher.dropped)
                cycle += 1
                stop.wait(args.interval)
        finally:
            publisher.flush(timeout=1)
            LOG.info("Simulator stopped queued=%s dropped=%s (queue is volatile)", len(publisher.pending), publisher.dropped)
            client.disconnect()
            client.loop_stop()
    else:
        # MQTT callback runs on the network thread; create/use SQLite there.
        received = 0
        storage_failed = False
        store = None
        client = make_client(os.getenv("MQTT_CLIENT_ID", "iot-ops-consumer"), manual_ack=True, tls=tls_identity())
        def connected(c, userdata, flags, reason_code, properties):
            if reason_code == 0:
                c.subscribe("iot-ops/devices/+/telemetry", qos=1)
                LOG.info("Subscribed to telemetry")
            else:
                LOG.error("MQTT connection rejected: %s", reason_code)
        def message(c, userdata, msg):
            nonlocal received, store, storage_failed
            try:
                if len(msg.payload) > 16384:
                    raise ValueError("Payload exceeds 16 KiB")
                payload = json.loads(msg.payload)
                if store is None:
                    store = TelemetryStore(args.db, args.max_rows)
                new = store.process(payload, msg.topic)
            except (json.JSONDecodeError, ValueError, ValidationError, UnicodeDecodeError) as error:
                # Poison messages must not crash the subscriber or be retried forever.
                LOG.error("Rejected message topic=%s error=%s", msg.topic, error)
                if msg.qos:
                    c.ack(msg.mid, msg.qos)
                return
            except (sqlite3.Error, OSError) as error:
                LOG.error("Storage failed; stopping without acknowledgment: %s", error)
                storage_failed = True
                stop.set()
                return
            if msg.qos:
                c.ack(msg.mid, msg.qos)  # Commit succeeded before acknowledging delivery.
            received += int(new)
            LOG.info("processed device=%s sequence=%s new=%s total=%s", payload["device_id"], payload["sequence"], new, received)
            if args.max_messages and received >= args.max_messages:
                stop.set()
        client.on_connect = connected
        client.on_message = message
        start(client)
        try:
            while not stop.wait(0.2):
                pass
        finally:
            client.disconnect()
            client.loop_stop()
            # Connection belongs to callback thread; it closes when process exits.
        if storage_failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
