# Migration Notes

Apply `001_initial_backend_platform.sql` first. It defines shared extensions, enums, tables, triggers, RBAC helper functions, and row-level-security policies used by later migrations.

The current planning pack has independent extension migrations after `001_`:

- `002_health_device_integrations.sql`
- `003_channels_calls_escalation.sql`
- `004_security_lint_fixes.sql`
- `005_performance_lint_fixes.sql`
- `006_drop_generated_duplicate_indexes.sql`

The extension migrations depend on `001_initial_backend_platform.sql`, and the lint-fix migrations depend on the complete schema produced by `001_` through `003_`. Before wiring these into Alembic, Flyway, or another ordered migration runner, keep the same ordering or convert them into proper revision IDs.

Recommended final order:

1. `001_initial_backend_platform.sql`
2. `002_health_device_integrations.sql`
3. `003_channels_calls_escalation.sql`
4. `004_security_lint_fixes.sql`
5. `005_performance_lint_fixes.sql`
6. `006_drop_generated_duplicate_indexes.sql`

The order above keeps ingestion/metric primitives available before channel escalation simulation tests reference device-generated risk scenarios.

## Supabase project

The hosted Supabase project created for this branch is:

- Name: `careagent-backend`
- Ref: `kgkfrrffrjfltswwcsmw`
- Region: `ap-south-1`

See `docs/supabase-deployment.md` for application and validation commands.

## RLS baseline

Every table in the exposed `public` schema must have RLS enabled. PHI-bearing tables are patient scoped with policies based on backend-set `app.user_id` and `app.role` settings. Catalogue/configuration tables are read-only where safe and admin-scoped for writes. Internal operational tables such as `audit_logs`, `idempotency_keys`, and `outbox_events` remain RLS protected because they may carry PHI or PHI-derived response metadata.
