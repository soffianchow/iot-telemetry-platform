# Manual sensor panel

An operator-driven alternative to the scheduled simulator. Each plot holds a crop profile,
sensor values, equipment state and fault toggles; a reading is published **only** when
the operator presses Send. Nothing is emitted on a timer, so the receiving stack sees
exactly the scenarios being tested.

Readings use the same topic, schema and validation as [MQTT](MQTT.md). Every payload
is validated before it is queued, so the panel cannot publish a reading the consumer
would reject.

## Run

```sh
make panel   # http://127.0.0.1:8088, plots from config/panel-devices.json
```

`python -m iot_ops panel --config <file> --host <addr> --port <port> [--allowed-host <name>]`.
The default bind is loopback. For remote use, bind to one specific interface, such as a
VPN or overlay address, rather than `0.0.0.0`: the panel has no authentication.

### Separate panel host (for example a Raspberry Pi)

The broker stays bound to loopback on the receiving machine. The receiving machine opens
an SSH reverse tunnel, so the panel host reaches the broker on its own loopback port:

```sh
# Receiving machine: broker + processor only, scheduled simulator stopped
make receiver
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -R 127.0.0.1:1883:127.0.0.1:1883 <user>@<panel-host>

# Panel host (Python 3.11+)
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
.venv/bin/pip install --no-deps -e .
MQTT_HOST=127.0.0.1 .venv/bin/python -m iot_ops panel --host <overlay-ip> --port 8088 \
  --allowed-host <dns-name>   # optional, for each extra name the UI is opened by
```

If the tunnel drops, the panel reports the broker as offline and queues readings in its
bounded, volatile buffer until the connection returns.

## Model

| Control | Effect on the next reading |
|---|---|
| Crop | Presets temperature, humidity, soil moisture and light to the middle of the crop's target range; sets the auto-irrigation threshold |
| Sensors | Reported directly; the UI highlights values outside the crop target |
| Pump mode | `auto` runs below the crop's minimum soil moisture; `on`/`off` override. Each reading sent with the pump running adds 2% soil moisture and draws 1% from the tank. An empty tank stops the pump |
| Tank, battery, signal | Reported directly; battery drains slightly per reading |
| Heat anomaly | Adds 14 °C to temperature and sets `anomaly` quality |
| Temp sensor failure | Null temperature with `sensor_failure` quality |
| Pump fault | `pump_state=fault`, no pumping |
| Offline | Readings are queued (marked offline) and forwarded in order once the fault is cleared and the plot sends again |
| Drop reading | Nothing is published, but the sequence advances so the consumer records a gap |

Crop profiles: lettuce, tomato, chili, strawberry. Edit
[panel-devices.json](../config/panel-devices.json) to change plot IDs and starting crops.

## HTTP API

| Method | Path | Body |
|---|---|---|
| GET | `/` | Touch UI |
| GET | `/api/state` | — (read only; never publishes) |
| POST | `/api/devices/<id>` | Any of `crop`, `pump_mode`, `faults`, sensor or equipment fields |
| POST | `/api/send` | `{"devices": ["plot-01"]}` or `{"all": true}` |

Out-of-range or unknown fields return 400 and leave the plot unchanged; unknown plots return 404.

## Request protections

- Requests must name an allowed host (the bind address, loopback, or `--allowed-host`), and
  any `Origin` header must match one, which blocks DNS rebinding and cross-site writes.
- POST bodies must be `application/json` and at most 4 KiB; other content types return 415.
- Wrong field types or values return 400 without changing state. Idle clients time out after 10 s.
- The UI is served with a hash-pinned Content-Security-Policy, `nosniff` and frame denial, and
  renders server data with `textContent` only.

## Limits

- No authentication or TLS on the panel; bind it to a trusted interface only.
- Settings live in memory and reset to crop defaults when the process restarts.
- The physical model is deliberately simple and is not agronomic guidance.

## Optional MQTT mutual TLS

The panel can hold one MQTT connection per plot with `MQTT_TLS_CA` and `MQTT_CERT_DIR`.
Each plot then uses its own client certificate and ID. See the [TLS contract and test
runner](MQTT.md#tls-and-device-identity) for configuration and verification. This protects
the MQTT transport; it does not add TLS or authentication to the panel's HTTP listener.
