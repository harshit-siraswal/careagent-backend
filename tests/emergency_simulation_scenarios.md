# Emergency Simulation Test Scenarios

These scenarios validate prompt 05 without contacting real channel providers or emergency services. They should run with `mock_simulator` provider configs and `escalation_policies.simulation_mode = true`.

## Test Harness Requirements

- Use deterministic synthetic risk events.
- Use simulator provider callbacks for push, WhatsApp, Telegram, SMS, and voice.
- Verify every outbound attempt creates an audit event.
- Verify no production provider is called during simulation.
- Verify every test has a stable idempotency key.
- Verify PHI appears only in approved template/script variables.

## Scenario Matrix

| Scenario | Purpose | Expected Result |
| --- | --- | --- |
| `critical_hr_primary_ack` | Critical heart-rate event reaches primary caretaker and receives acknowledgement | Run completes as `acknowledged`; no secondary or emergency contact is called |
| `critical_hr_no_ack_fallback` | Primary caretaker does not acknowledge | Fallback reaches secondary caretaker, then doctor; run completes when doctor acknowledges |
| `duplicate_critical_event` | Repeated request uses same idempotency key | Existing escalation run is returned; no duplicate dispatch attempts are created |
| `revoked_voice_consent` | Voice consent was revoked before critical event | Voice steps are skipped with policy-denied reason; non-voice fallback continues |
| `unverified_telegram_ack` | Telegram chat is not verified | Telegram acknowledgement is rejected; run remains awaiting valid acknowledgement |
| `whatsapp_template_not_approved` | Production WhatsApp template is not approved | WhatsApp dispatch is blocked and fallback channel is selected |
| `patient_cancels_after_push` | Patient cancels false alarm after first push | Later actions are cancelled; run records cancellation actor and reason |
| `location_consent_absent` | Escalation tries to include location without consent | Location variables are omitted; dispatch still proceeds if policy allows message without location |
| `simulation_emergency_contact_block` | Policy includes public emergency number in simulation | Emergency call is simulated only; real provider adapter is not invoked |

## Assertions

For every scenario:

- `escalation_runs.status` reaches the expected terminal state.
- `escalation_actions` reflect ordered step execution and skipped steps.
- `channel_dispatch_attempts.simulation = true`.
- `delivery_receipts.signature_valid = true` for simulator callbacks.
- `call_events` record DTMF/speech acknowledgements without storing full raw provider payloads.
- `audit_logs` include policy decision, message/call attempt, provider receipt, and acknowledgement or cancellation.
- `risk_events.status` is updated consistently with escalation outcome.

## Negative Tests

- A direct dispatch request without `policy_decision_id` returns `403`.
- A WhatsApp business-initiated production message using a draft template returns `403`.
- A voice call request using a script without AI disclosure is rejected by template/script validation.
- A Telegram `/summary` command from an unlinked chat returns only verification instructions.
- A retry after a hard provider failure does not occur.
- A second emergency-service action in the same run is blocked unless policy explicitly allows repeats.
