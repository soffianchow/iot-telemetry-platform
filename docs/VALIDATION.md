# Validation results

The following evidence was recorded on 2026-10-23 for the Phase 1 implementation.
This is a local integration reference system; AWS resources have not been deployed.

| Check | Result | Scope |
|---|---|---|
| Python tests | 37 passed | 29 unit tests and 8 Lambda handler tests |
| Docker tests | 31 passed | 29 unit tests and 2 actual MQTT integration tests |
| Terraform | Passed | Formatting, provider initialization and configuration validation |
| Lambda package | Passed | Handler and shared schema imported in Linux ARM64 Python 3.12 |
| Broker outage drill | Recovered | Six-second broker stop; ingestion resumed automatically |
| GitHub Actions | Passed | Python, Docker/MQTT and Terraform validation jobs |

[CI evidence for the implementation](https://github.com/soffianchow/iot-telemetry-platform/actions/workflows/validate.yml).
The provider lock includes macOS ARM64 and Linux AMD64 package checksums.

## Mutual TLS verification — 2026-11-10

| Check | Result | Scope |
|---|---|---|
| Python tests | 113 passed | 105 unit tests and 8 Lambda handler tests |
| Mutual-TLS integration | 6 passed | Real certificate verification, device topic ACLs and panel identities |
| Plaintext Docker regression | 107 passed, 6 skipped | 105 unit and 2 MQTT tests; TLS tests run separately |

The TLS suite first proves a valid client can connect, then checks that missing client
certificates, an untrusted CA and a wrong server hostname are rejected. It also checks
own-topic publishing, cross-device denial, claimed-ID isolation and two independent
panel connections. The test broker and certificates are temporary and removed on exit.
These results establish local Mosquitto behavior; they do not establish AWS authorization.

## Reproduce

```sh
make setup
make test
uv run pytest -q infra/terraform/modules/lambda/test_handler.py
make integration
make tls-test
make terraform
uv run python infra/terraform/build_lambda.py
```

Integration tests use their own Compose project, broker and volumes, separate from the
demo stack. They exercise malformed JSON rejection, topic/payload identity enforcement,
ten-device ingestion, duplicate handling, bounded buffering and transport reconnection.

The outage drill recorded stored rows increasing from 394 to 464 after recovery, with
10 devices present. Observed events included anomaly, high temperature, offline state,
pump fault, sensor failure and sequence gaps. These are sample run observations, not
throughput or availability benchmarks.

Manual panel run (panel and consumer against an isolated broker): no messages were stored
while idle; one plot sent with dry soil reported the pump running and soil rising 2% per
reading; an offline plot queued its reading and forwarded it in sequence after the fault
was cleared. A separate run on a Raspberry Pi (Python 3.13, aarch64) passed the unit
suite and published through an SSH reverse tunnel to the Compose processor.

## Limits of the evidence

- Terraform validation does not test AWS permissions, quotas or live service behavior.
- Producer buffering is volatile; overflow and process failure can lose readings.
- Local high-water deduplication discards older out-of-order readings.
- No load, production availability, physical sensor calibration or mobile SSH test is claimed.
- See [architecture](ARCHITECTURE.md) and [AWS design](AWS.md) for delivery and security limits.
