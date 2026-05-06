param(
  [string]$DatabaseUrl = $env:SUPABASE_DB_URL,
  [string]$ProjectRef = "kgkfrrffrjfltswwcsmw",
  [string]$PsqlPath = "psql"
)

$ErrorActionPreference = "Stop"

$validationSql = @"
select current_database() as database_name, current_setting('server_version') as postgres_version;

select table_name
from information_schema.tables
where table_schema = 'public'
  and table_type = 'BASE TABLE'
  and table_name not like 'pg_%'
except
select c.relname
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and c.relrowsecurity = true
order by table_name;

select c.relname as rls_table_without_policy
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
left join pg_policy p on p.polrelid = c.oid
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and c.relrowsecurity = true
group by c.relname
having count(p.oid) = 0
order by c.relname;

select c.relname as table_name, count(p.oid) as policy_count
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
left join pg_policy p on p.polrelid = c.oid
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
group by c.relname
order by c.relname;

select obj_description(('public.' || table_name)::regclass, 'pg_class') is not null as has_comment,
       table_name
from information_schema.tables
where table_schema = 'public'
  and table_type = 'BASE TABLE'
order by table_name;

select tgrelid::regclass as protected_table, tgname
from pg_trigger
where tgname = 'audit_logs_no_update';
"@

if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
  Write-Host "No database URL supplied. Validation SQL for project ${ProjectRef}:"
  Write-Output $validationSql
  exit 0
}

$psqlCommand = Get-Command $PsqlPath -ErrorAction SilentlyContinue
if (-not $psqlCommand) {
  throw "psql was not found. Install PostgreSQL client tools or pass -PsqlPath with the full path to psql."
}

Write-Host "Running CareAgent Supabase validation queries against project $ProjectRef"
& $psqlCommand.Source `
  --set ON_ERROR_STOP=1 `
  --dbname $DatabaseUrl `
  --command $validationSql

if ($LASTEXITCODE -ne 0) {
  throw "Validation queries failed."
}
