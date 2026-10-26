# Roadmap

Phase 1 stops at a verified local system and undeployed infrastructure scaffolding.
The following milestones describe proposed development beyond the local implementation.

## Phase 2 — AWS integration

- Review budget, region, pricing and quotas; establish budget alerts.
- Issue per-device certificates securely, enforce TLS and test identity-to-topic binding.
- Deploy reviewed IaC into an isolated account; test real IoT → Lambda → DynamoDB flow.
- Exercise denied permissions, malformed payloads, duplicate events and delivery failures.
- Define replay/dead-letter handling, costs, retention and teardown evidence.

## Phase 3 — operations and DevOps

- Metrics for accepted/rejected/duplicate messages, device freshness and sequence gaps.
- Dashboard, actionable alerts, SLOs, load tests, failure drills and incident runbooks.
- GitHub OIDC with environment approvals; no long-lived credentials.
- Signed artifacts, dependency update automation and restore/replay testing.

## Phase 4 — reusable profiles and AI operations

- Asset profiles for manufacturing vibration, facility water/air and agricultural irrigation.
- Read-only AI incident summaries grounded in telemetry and runbooks with provenance.
- Human approval and audit trail for any actuation; never let an LLM directly control a pump.
- Evaluate false positives, missed incidents, hallucinated explanations and cost per incident.

Release criteria: reproducible builds, measured behavior under failure,
reviewable security decisions, truthful evidence and a short recorded demonstration.
