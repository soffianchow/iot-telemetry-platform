# Engineering decisions

**MQTT** decouples device producers from consumers using topics and a broker. QoS 1
means at-least-once transport delivery; it does not mean an application committed the
message. Sequence numbers expose gaps. Idempotent storage handles redelivery.

**A simulator with state** is useful for testing operations. Smooth daily patterns and
bounded drift distinguish ordinary changes from injected faults. Fixed seeds make an
incident repeatable. The model is illustrative, not a calibrated physical digital twin.

**Local SQLite** makes ingestion observable without a managed database bill. It is a
single-process lab store, not a horizontally scalable replacement for DynamoDB.

**Terraform modules** separate device identity, rule routing, compute, storage,
permissions and monitoring. Variables describe interfaces; outputs connect modules.
`init` installs providers; `fmt` normalizes HCL; `validate` checks configuration structure.
Validation does not prove account permissions, service quotas, runtime behavior or cost.
No plan/apply or AWS credentials are needed for this phase.

**Serverless target** avoids permanently running cloud compute: IoT Core accepts
messages, Rules route them, Lambda validates/processes them, and DynamoDB stores
queryable records with expiry. CloudWatch records errors and supports alarms. Services
still cost money when provisioned or used; free tier is not a cost guarantee.

**CI** makes the local proof repeatable on a clean runner. Dependency locks and image
versions reduce drift. Tests need to prove failure behavior, not just successful imports.

## References

- [Mosquitto authentication](https://mosquitto.org/documentation/authentication-methods/)
- [AWS IoT Rules](https://docs.aws.amazon.com/iot/latest/developerguide/iot-rules.html)
- [Terraform validation](https://developer.hashicorp.com/terraform/cli/commands/validate)
- [MQTT specification](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html)
