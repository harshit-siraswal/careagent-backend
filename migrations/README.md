# Migration Notes

Apply `001_initial_backend_platform.sql` first. It defines shared extensions, enums, tables, triggers, RBAC helper functions, and row-level-security policies used by later migrations.

The current planning pack has independent extension migrations after `001_`:

- `002_health_device_integrations.sql`
- `003_channels_calls_escalation.sql`

Both depend on `001_initial_backend_platform.sql` and can be reviewed independently. Before wiring these into Alembic, Flyway, or another ordered migration runner, give them a final sequence number such as `002_...` and `003_...` or convert them into proper revision IDs.

Recommended final order:

1. `001_initial_backend_platform.sql`
2. Health-device connector/metric extensions.
3. Channel, call, dispatch, and emergency simulation extensions.

The order above keeps ingestion/metric primitives available before channel escalation simulation tests reference device-generated risk scenarios.
