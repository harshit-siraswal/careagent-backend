param(
  [string]$DatabaseUrl = $env:SUPABASE_DB_URL,
  [string]$ProjectRef = "kgkfrrffrjfltswwcsmw",
  [string]$MigrationsPath = (Join-Path $PSScriptRoot "..\migrations"),
  [string]$PsqlPath = "psql"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
  throw "Set SUPABASE_DB_URL or pass -DatabaseUrl. Use a Postgres connection string for project $ProjectRef; do not use a service_role JWT."
}

$psqlCommand = Get-Command $PsqlPath -ErrorAction SilentlyContinue
if (-not $psqlCommand) {
  throw "psql was not found. Install PostgreSQL client tools or pass -PsqlPath with the full path to psql."
}

$orderedMigrations = @(
  "001_initial_backend_platform.sql",
  "002_health_device_integrations.sql",
  "003_channels_calls_escalation.sql"
)

foreach ($migration in $orderedMigrations) {
  $path = Join-Path $MigrationsPath $migration
  if (-not (Test-Path -LiteralPath $path)) {
    throw "Missing migration file: $path"
  }
}

Write-Host "Applying CareAgent Supabase migrations to project $ProjectRef"

foreach ($migration in $orderedMigrations) {
  $path = Resolve-Path -LiteralPath (Join-Path $MigrationsPath $migration)
  Write-Host "Applying $migration"

  & $psqlCommand.Source `
    --set ON_ERROR_STOP=1 `
    --dbname $DatabaseUrl `
    --file $path.Path

  if ($LASTEXITCODE -ne 0) {
    throw "Migration failed: $migration"
  }
}

Write-Host "Migrations applied successfully."
