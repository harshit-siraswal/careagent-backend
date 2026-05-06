# Risk Engine Implementation

This module is deterministic by design. Agent or LLM output may describe context, draft messages, or request a backend tool, but it does not approve medical risk events, voice calls, emergency escalation, or location sharing.

## Rule Model

Rules are versioned `RiskRule` objects with:

- `rule_key` and `version` for auditability and idempotency.
- `severity`, `metric_codes`, and machine-readable `conditions`.
- `required_reliability`, `rationale`, and optional reviewer metadata for clinical review.

The initial rules cover SpO2, glucose, heart rate, blood pressure, temperature, fall detection, and stale observation quality notices. Patient-specific thresholds can be introduced by passing a different rule set into `evaluate_observations`.

## Source Quality

Each observation is scored from source reliability, device freshness, and observation confidence.

- Clinical and standard BLE sources score highest.
- OS aggregators and vendor APIs are usable but carry source metadata.
- Manual/OCR observations are lower reliability and require confirmation for high-risk actions.
- Stale readings become low-severity data-quality events and must not trigger emergency escalation as live deterioration.

Risk evidence includes metric, value, unit, source, observed timestamp, rule version, freshness, reliability tier, score, and quality flags.

## Idempotency

Risk event keys use:

```text
risk:{patient_id}:{rule_key}:v{version}:{minute_window}:{evidence_hash}
```

Helpers also provide outbox event keys and escalation keys matching the queue contract.

## Policy Gates

`app.services.policy` enforces deterministic gates for critical actions:

- All tools require `agent:tool_call` plus tool-specific scope.
- Voice calls require active voice consent.
- Critical escalation requires emergency policy enablement and emergency consent.
- Location is omitted unless consent and policy both allow it.
- Simulation mode is carried in decisions so drills do not invoke production emergency services.

Denied decisions are built for audit as `agent.tool_denied`. Approved decisions are still auditable and include the policy decision payload.
