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
