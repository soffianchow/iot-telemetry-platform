# Architecture and operational boundaries

The local path is simulator → Mosquitto → validator/processor → SQLite → operator CLI.
The AWS target substitutes IoT Core, a Rule, Lambda, DynamoDB and CloudWatch. Local
implementation demonstrates message contracts and failure behavior; it is not an AWS emulator.

## Data and device behavior

Ten configurable devices share a versioned JSON contract. Temperature, humidity,
light and RSSI follow smooth periodic curves with device phase offsets. Soil, tank and
battery evolve with state; pump behavior affects water use. Simulation cycles accelerate
environmental time while timestamps retain real UTC event time. Fault windows repeat
predictably. See [MQTT](MQTT.md) for the contract, units and fault controls.

## Delivery and storage

Publish and subscribe use MQTT QoS 1. The producer reconnects with bounded delay and
buffers at most 1,000 readings by default; overflow drops the oldest and logs a counter.
Paho inflight and transport queues are also bounded. A simulated offline asset buffers
readings and sends its historical offline-marked samples on recovery, not during the outage.
Missing-message injection intentionally omits samples and advances sequence numbers.

The consumer has a persistent MQTT session and acknowledges only after SQLite commits.
Malformed JSON/schema/topic mismatches are logged and discarded. Storage errors stop
the consumer with failure so Compose can restart it. Mosquitto persists sessions/queued
messages in its own named volume, with a 30-second autosave interval and bounded queue.
Persistence does not guarantee zero loss after abrupt host/power failure.

SQLite retains at most 10,000 telemetry rows and 10,000 event rows by default, plus the
latest record/high-water mark for each encountered device. Its high-water policy treats
older or repeated sequence numbers as stale: useful for a latest-value lab, but it discards
legitimate out-of-order history. The latest-device table is not globally bounded for an
untrusted unlimited identity stream. The trusted local simulator has ten assets. Cloud
Lambda separately enforces the configured device allowlist.

Producer sequence numbers start from wall-clock microseconds and increment per sample;
normal restarts avoid collisions, but clock rollback or two simultaneous producers for one
device can break ordering. A durable boot/session identity is a future improvement.
Large restart gaps do not count missing messages accurately. Sequence is capped at
2^53−1 for interoperability and safe storage. Event flags record faults/thresholds/gaps;
status reports freshness (stale after 30 seconds), not an alerting service.

## Security and resources

The lab uses anonymous, unencrypted MQTT inside its local Docker network. The host
listener binds loopback only. Remote inspection can use an SSH tunnel without publishing broker ports. App containers run without root, drop capabilities, use a read-only
filesystem and persist only their data volume. Docker logs rotate. Local credentials are
optional environment inputs and must never be committed.

The Terraform target uses per-device publish-only topic policies, scoped Lambda
invocation and storage/logging IAM permissions, a disabled rule, bounded concurrency,
seven-day telemetry TTL and log retention. No certificates/private keys or credentials are
created in Phase 1. Full TLS/certificate lifecycle, cloud replay/error destinations and alarm
notifications require a later deployment. See [AWS](AWS.md).

## Verification boundaries

Unit tests cover deterministic faults, validation, bounded storage, queue behavior and
consumer error handling. Integration tests use a real broker and consumer process to
prove malformed-message survival, topic identity rejection, ten-device storage,
deduplication and buffered transport reconnect. Terraform validation checks structure only.
No scalability, cloud availability, real sensor accuracy or production security claim is made.
