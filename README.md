# CareAgent Backend Contract Package

This directory contains the backend API and data-platform contract for the CareAgent MVP. It is designed for a FastAPI, PostgreSQL, Redis/queue, object-storage, and background-worker implementation.

## Contents

- `migrations/001_initial_backend_platform.sql` - PostgreSQL schema for auth identities, patient-scoped RBAC, consent ledger, observations, documents, medicines, risk, escalation, agent calls, outbox events, idempotency, and audit logs.
- `migrations/002_health_device_integrations.sql` - Device connector, metric catalog, sync, freshness, and integration extensions.
- `migrations/003_channels_calls_escalation.sql` - Channel provider, template/script, dispatch, receipt, call event, acknowledgement, and escalation simulation extensions.
- `migrations/004_security_lint_fixes.sql` - Supabase advisor security hardening for function search paths, private RLS helper placement, and extension schema placement.
- `migrations/005_performance_lint_fixes.sql` - Missing foreign-key index creation and RLS policy split for read-heavy catalog tables.
- `migrations/006_drop_generated_duplicate_indexes.sql` - Cleanup for generated FK indexes when a hand-named index already covers the same columns.
- `migrations/007_add_supabase_auth_provider.sql` - Adds Supabase Auth as an allowed auth identity provider.
- `migrations/008_add_supabase_auth_bridge.sql` - Syncs Supabase Auth users into CareAgent account and identity tables and lets RLS helpers fall back to Supabase JWT claims.
- `migrations/README.md` - Notes on applying and eventually renumbering independent extension migrations.
- `openapi/careagent-backend-v1.yaml` - API route list with request/response schemas and route-level authorization/audit annotations.
- `openapi/channels-calls-escalation.openapi.yaml` - Channel linking, dispatch, webhook, and emergency simulation route extensions.
- `openapi/health-device-integrations.yaml` - Device catalog, connector account, sync, freshness, and simulator route extensions.
- `docs/authorization-matrix.md` - role and patient-scope authorization rules.
- `docs/queue-event-design.md` - outbox, queue, worker, and event payload design.
- `docs/audit-events.md` - audit event catalogue and required audit semantics.
- `docs/remaining-backend-work-report.md` - current backend implementation gap report and production-readiness blockers.
- `tests/backend-contract-test-plan.md` - unit and integration test plan for the backend implementation.
- `tests/emergency_simulation_scenarios.md` and `tests/emergency_simulation_cases.json` - Scenario-driven escalation simulation fixtures.
- `scripts/apply_migrations.ps1` - Applies the SQL migrations in order with `psql` and a supplied Postgres connection URL.
- `scripts/validate_migrations.ps1` - Runs validation queries for RLS, policies, comments, and audit immutability.
- `docs/supabase-deployment.md` - Supabase project deployment notes for `careagent-backend` (`kgkfrrffrjfltswwcsmw`, `ap-south-1`).
- `docs/supabase-google-auth.md` - Google OAuth setup for Supabase Auth and Flutter redirect configuration.

## Non-Negotiable Backend Invariants

1. Every request is authenticated unless the OpenAPI route explicitly sets `security: []`.
2. Every patient-scoped route must resolve exactly one `patient_id` from path, body, or loaded resource before accessing PHI.
3. Role checks are not enough; non-patient actors also need an active `patient_access_grants` row with the required permission.
4. Every PHI read, PHI write, consent change, agent tool call, message, call, webhook side effect, and escalation action writes an `audit_logs` row.
5. Escalation starts, risk-event creation, document upload sessions, webhook side effects, and outbound actions use idempotency keys.
6. Raw documents are uploaded directly to object storage and remain blocked from OCR/extraction/download until malware scan is clean.
7. Observation writes are batched, partitioned by time, indexed by `(patient_id, metric_code, observed_at desc)`, and emitted through the outbox for risk processing.

## Backend API Skeleton

This branch includes a minimal FastAPI skeleton for local contract iteration. It does not integrate a real auth provider, database, object storage, or queue yet. Auth, patient scope, and audit behavior are placeholder hooks:

- Authenticated routes require `Authorization: Bearer <token>`.
- The placeholder actor is supplied with `X-CareAgent-Role`, `X-CareAgent-Patient-Id`, and `X-CareAgent-Permissions`.
- PHI routes call patient-scope checks and append audit events to request state.
- Idempotent stubs such as document upload and escalation start require `Idempotency-Key`.

Run locally:

```powershell
python -m pip install -e ".[test]"
python -m uvicorn app.main:app --reload
```

Verify locally:

```powershell
python -m compileall app
python -m pytest
```

## Supabase Migration Quickstart

Project ref: `kgkfrrffrjfltswwcsmw` (`careagent-backend`, `ap-south-1`).

```powershell
$env:SUPABASE_DB_URL = "postgresql://postgres:<password>@db.kgkfrrffrjfltswwcsmw.supabase.co:5432/postgres"
.\scripts\apply_migrations.ps1
.\scripts\validate_migrations.ps1
```

The scripts use a Postgres connection string and do not assume a Supabase `service_role` JWT is available.
