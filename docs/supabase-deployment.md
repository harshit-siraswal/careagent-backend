# Supabase Deployment

CareAgent backend Supabase project:

- Project name: `careagent-backend`
- Project ref: `kgkfrrffrjfltswwcsmw`
- Region: `ap-south-1`
- Postgres: Supabase hosted Postgres 17

## Migration Order

Apply migrations in this order:

1. `migrations/001_initial_backend_platform.sql`
2. `migrations/002_health_device_integrations.sql`
3. `migrations/003_channels_calls_escalation.sql`

The migrations assume a fresh database or a database where Supabase migration history prevents re-applying the same files. Do not re-run them manually against an already migrated database unless you have confirmed the target schema state.

## Applying With psql

The local helper script uses a Postgres connection string. It does not require, accept, or assume a Supabase `service_role` JWT.

```powershell
$env:SUPABASE_DB_URL = "postgresql://postgres:<password>@db.kgkfrrffrjfltswwcsmw.supabase.co:5432/postgres"
.\scripts\apply_migrations.ps1
```

If `psql` is not on `PATH`, pass the full path:

```powershell
.\scripts\apply_migrations.ps1 -PsqlPath "C:\Program Files\PostgreSQL\17\bin\psql.exe"
```

## Validation

Run:

```powershell
.\scripts\validate_migrations.ps1
```

Without `SUPABASE_DB_URL`, the script prints the validation SQL. With a database URL, it checks:

- Postgres server version.
- Public tables without RLS.
- RLS-enabled public tables without policies.
- Policy counts per public table.
- Table comments.
- The append-only `audit_logs` trigger.

## RLS Notes

All public tables are expected to have RLS enabled. PHI-bearing tables are patient scoped through `app_can_access_patient(...)`, which reads backend-set session variables:

- `app.user_id`
- `app.role`

Backend request handling must set these variables inside the transaction before accessing patient-scoped tables. Worker and privileged maintenance paths should use database credentials that intentionally bypass RLS rather than weakening table policies.

Do not store provider secrets in public tables. Channel provider rows use `secret_ref`, and connector accounts use `token_vault_ref` for external secret storage references.
