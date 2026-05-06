# Channels and Escalation Implementation

This workstream adds a provider-agnostic Python implementation for channel dispatch, template rendering, voice call scripts, ordered escalation fallback, idempotency, and emergency simulations.

## Modules

- `app/domain/channels.py` defines channel, provider, template, call-script, delivery, and dispatch status enums and dataclasses aligned to `003_channels_calls_escalation.sql` and the OpenAPI extension.
- `app/services/channels.py` provides a JSON-backed template library, idempotent dispatcher, and mock provider adapters for WhatsApp, Telegram, push, SMS, email, and voice.
- `app/domain/escalation.py` defines escalation policies, steps, runs, actions, acknowledgements, consent, and simulation result models.
- `app/services/escalation.py` provides an in-memory escalation engine and fixture-backed emergency simulation runner.

## Production Constraints

Real provider adapters are intentionally not implemented here. Production wiring must use official WhatsApp Business Cloud API or an approved BSP, verified Telegram Bot webhooks, push providers such as FCM/APNS, approved SMS/email gateways, and compliant programmable voice providers.

Prototype WhatsApp Web style providers must remain `prototype_only` and cannot run with `provider_environment = production`.

Business-initiated WhatsApp messages require approved templates. The dispatcher blocks non-approved production templates.

Telegram medical commands and acknowledgements require verified `ChannelLink` records. Unverified acknowledgements are rejected and the escalation remains awaiting a valid acknowledgement.

Voice scripts must disclose AI identity. The call script validator rejects scripts that do not include an AI disclosure.

Emergency-service and public emergency-number steps require active emergency consent and a policy with `emergency_enabled = true`. Simulation mode never invokes real providers.

Location variables are omitted unless both consent and policy allow location sharing.

## Idempotency

`ChannelDispatcher` stores dispatch attempts by request idempotency key and returns the original attempt on replay.

`EscalationEngine` stores runs by both `idempotency_key` and `(risk_event_id, policy_id)`, matching the queue design. Duplicate start requests return the existing run and do not create duplicate dispatch attempts.

## Tests

The tests cover template rendering, policy-denied direct dispatch, WhatsApp template approval, AI disclosure scripts, ordered fallback acknowledgement, revoked voice consent, Telegram verification checks, location omission, and fixture-backed emergency simulation.
