# MQTT contract and configuration

Topic: `iot-ops/devices/<device_id>/telemetry`, QoS 1, non-retained. Consumer wildcard:
`iot-ops/devices/+/telemetry`. The broker health check uses the separate `health` topic.
Payload device identity must equal the topic segment. Device IDs allow letters, digits,
hyphens and underscores, 1–64 characters. Schema version is 1.

Canonical wire schema: [telemetry.schema.json](../schemas/telemetry.schema.json).
The packaged copy inside src/iot_ops is verified equal in unit tests.

```json
{
  "schema_version": 1,
  "device_id": "device-001",
  "timestamp": "2026-10-23T02:30:00Z",
  "sequence": 42,
  "signal_strength_dbm": -62.0,
  "connectivity": "online",
  "quality": [],
  "metrics": {
    "temperature_c": 25.0,
    "humidity_pct": 65.0,
    "soil_moisture_pct": 49.0,
    "light_lux": 18000.0,
    "tank_level_pct": 88.0,
    "pump_state": "on",
    "battery_pct": 99.9
  }
}
```

Percent fields range 0–100; light is lux, temperature Celsius, RSSI dBm. Temperature
may be null only with `sensor_failure` quality. `pump_state=fault` requires `pump_fault`.
Offline connectivity requires `offline` quality. Timestamps require timezone information;
the simulator emits UTC. Sequence is a nonnegative integer capped at 2^53−1. Extra
properties and invalid metric bounds are rejected; see schema for precise bounds.

Edit [devices.json](../config/devices.json) and rebuild to change device count, IDs and
fault schedules. Each device has `device_id` and optional `faults`. A fault has `kind`,
`start_cycle`, positive `duration_cycles`, optional `repeat_every` >= duration. Kinds:

| Kind | Behavior |
|---|---|
| anomaly | raises temperature during fault window |
| offline | buffers historical readings until that asset reconnects |
| sensor_failure | null temperature plus quality marker |
| missing | deliberately omits messages; sequence still increments |
| pump_fault | pump fault state, no simulated pumping |

Default faults start at cycles 8–17, last 3 cycles, repeat every 60 cycles. At the
2-second interval the first incident appears in about 16 seconds. State evolves per cycle;
changing interval changes the demo's speed, not its physical calibration.

`MQTT_HOST`, `MQTT_PORT`, optional `MQTT_USERNAME`/`MQTT_PASSWORD` configure Python
clients. `MQTT_CLIENT_ID` overrides the consumer's default persistent session ID
`iot-ops-consumer`; concurrent consumers need unique IDs. Persistent sessions accumulate
bounded queued messages while a subscriber is absent. They are not load-balancing.

CLI controls: `simulate --cycles N --interval SECONDS --buffer-size N`,
`consume --db PATH --max-rows N --max-messages N`, and `status --db PATH`.
`--max-messages` counts accepted unique rows. Infinite service mode is the default.

## TLS and device identity

Plain MQTT on loopback is the local default. Setting `MQTT_TLS_CA` switches every client
(simulator, consumer, panel) to TLS 1.2+ with a verified server certificate and hostname,
and the default port to 8883. Client certificates enable mutual TLS:

| Variable | Meaning |
|---|---|
| `MQTT_TLS_CA` | CA bundle used to verify the broker (for AWS IoT, the Amazon root CA) |
| `MQTT_TLS_CERT` / `MQTT_TLS_KEY` | One shared client certificate and key |
| `MQTT_CERT_DIR` | Per-device identities: `<device_id>.cert.pem` and `<device_id>.key.pem` |

With `MQTT_CERT_DIR`, the panel opens one connection per plot using the plot ID as client
ID, matching the per-device AWS IoT policy (connect only as itself, publish only to its own
topic). `MQTT_CERT_DIR` is used by the panel; the simulator and consumer need the shared
certificate pair instead. A directory-only configuration without a device identity fails
at startup rather than silently omitting the client certificate. When both modes are
configured, per-device panel sessions use the directory; clients without a device ID use
the shared pair. Partial certificate settings are rejected.

`make tls-test` starts a throwaway mutual-TLS Mosquitto broker with a per-identity topic
ACL. Mosquitto replaces the client ID with the certificate identity; AWS IoT instead
checks the requested client ID against the device policy. The local test proves topic
isolation, not exact AWS authorization behavior.

The suite verifies successful device publishing, rejection of connections without a
client certificate, cross-device publish denial, certificate identity taking precedence
over a claimed client ID, rejection of an untrusted CA and a wrong server hostname, and
independent panel connections. Positive controls first establish that the broker works.

The runner requires Docker, OpenSSL and uv. It binds only loopback on port 18884
(override with `TLS_TEST_PORT`), uses a digest-pinned Mosquitto image and removes only its
own container. All test private keys are owner-only. Only broker material is mounted into
the non-root, read-only container; the CA signing key is deleted before startup. Test
certificates are generated per run and removed on exit. No AWS credentials are involved.

This adds optional TLS client support and a reproducible test broker. The default Compose
broker is still local plaintext MQTT; this change does not turn its listener into TLS or
add authentication to the HTTP panel. Certificates, rotation and revocation for a deployed
system remain separate operational work.
