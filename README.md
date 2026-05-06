# CareAgent Backend Contract Package

This directory contains the backend API and data-platform contract for the CareAgent MVP. It is designed for a FastAPI, PostgreSQL, Redis/queue, object-storage, and background-worker implementation.

## Contents

- `migrations/001_initial_backend_platform.sql` - PostgreSQL schema for auth identities, patient-scoped RBAC, consent ledger, observations, documents, medicines, risk, escalation, agent calls, outbox events, idempotency, and audit logs.
- `migrations/002_health_device_integrations.sql` - Device connector, metric catalog, sync, freshness, and integration extensions.
- `migrations/003_channels_calls_escalation.sql` - Channel provider, template/script, dispatch, receipt, call event, acknowledgement, and escalation simulation extensions.
- `migrations/README.md` - Notes on applying and eventually renumbering independent extension migrations.
- `openapi/careagent-backend-v1.yaml` - API route list with request/response schemas and route-level authorization/audit annotations.
- `openapi/channels-calls-escalation.openapi.yaml` - Channel linking, dispatch, webhook, and emergency simulation route extensions.
- `openapi/health-device-integrations.yaml` - Device catalog, connector account, sync, freshness, and simulator route extensions.
- `docs/authorization-matrix.md` - role and patient-scope authorization rules.
- `docs/queue-event-design.md` - outbox, queue, worker, and event payload design.
- `docs/audit-events.md` - audit event catalogue and required audit semantics.
- `tests/backend-contract-test-plan.md` - unit and integration test plan for the backend implementation.
- `tests/emergency_simulation_scenarios.md` and `tests/emergency_simulation_cases.json` - Scenario-driven escalation simulation fixtures.
- `scripts/apply_migrations.ps1` - Applies the SQL migrations in order with `psql` and a supplied Postgres connection URL.
- `scripts/validate_migrations.ps1` - Runs validation queries for RLS, policies, comments, and audit immutability.
- `docs/supabase-deployment.md` - Supabase project deployment notes for `careagent-backend` (`kgkfrrffrjfltswwcsmw`, `ap-south-1`).

## Non-Negotiable Backend Invariants

1. Every request is authenticated unless the OpenAPI route explicitly sets `security: []`.
2. Every patient-scoped route must resolve exactly one `patient_id` from path, body, or loaded resource before accessing PHI.
3. Role checks are not enough; non-patient actors also need an active `patient_access_grants` row with the required permission.
4. Every PHI read, PHI write, consent change, agent tool call, message, call, webhook side effect, and escalation action writes an `audit_logs` row.
5. Escalation starts, risk-event creation, document upload sessions, webhook side effects, and outbound actions use idempotency keys.
6. Raw documents are uploaded directly to object storage and remain blocked from OCR/extraction/download until malware scan is clean.
7. Observation writes are batched, partitioned by time, indexed by `(patient_id, metric_code, observed_at desc)`, and emitted through the outbox for risk processing.

## Supabase Migration Quickstart

Project ref: `kgkfrrffrjfltswwcsmw` (`careagent-backend`, `ap-south-1`).

```powershell
$env:SUPABASE_DB_URL = "postgresql://postgres:<password>@db.kgkfrrffrjfltswwcsmw.supabase.co:5432/postgres"
.\scripts\apply_migrations.ps1
.\scripts\validate_migrations.ps1
```

The scripts use a Postgres connection string and do not assume a Supabase `service_role` JWT is available.
