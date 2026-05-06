-- Supabase performance advisor fixes.

BEGIN;

DO $$
DECLARE
  fk record;
  index_name text;
BEGIN
  FOR fk IN
    WITH fks AS (
      SELECT
        con.oid AS constraint_oid,
        con.conrelid AS table_oid,
        n.nspname AS schema_name,
        c.relname AS table_name,
        con.conname AS constraint_name,
        con.conkey::smallint[] AS conkey,
        array_length(con.conkey, 1) AS key_len,
        (
          SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY u.ord)
          FROM unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord)
          JOIN pg_attribute a
            ON a.attrelid = con.conrelid
           AND a.attnum = u.attnum
        ) AS column_list
      FROM pg_constraint con
      JOIN pg_class c ON c.oid = con.conrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE con.contype = 'f'
        AND n.nspname = 'public'
    )
    SELECT *
    FROM fks
    WHERE NOT EXISTS (
      SELECT 1
      FROM pg_index idx
      WHERE idx.indrelid = fks.table_oid
        AND idx.indpred IS NULL
        AND idx.indexprs IS NULL
        AND (
          SELECT array_agg(k.attnum::smallint ORDER BY k.ord)
          FROM unnest(idx.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
          WHERE k.ord <= fks.key_len
        ) = fks.conkey
    )
  LOOP
    index_name := left(
      format('idx_%s_%s', fk.table_name, fk.constraint_name),
      55
    ) || '_' || substr(md5(fk.constraint_oid::text), 1, 7);

    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I.%I (%s)',
      index_name,
      fk.schema_name,
      fk.table_name,
      fk.column_list
    );
  END LOOP;
END $$;

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'ble_profile_catalog',
    'connector_definitions',
    'device_catalog',
    'device_catalog_metric_support',
    'metric_catalog',
    'metric_normalization_rules',
    'risk_rules',
    'simulator_scenarios'
  ]
  LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS %I ON public.%I',
      table_name || '_admin_write_scope',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR INSERT WITH CHECK (public.app_is_admin())',
      table_name || '_admin_insert_scope',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR UPDATE USING (public.app_is_admin()) WITH CHECK (public.app_is_admin())',
      table_name || '_admin_update_scope',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR DELETE USING (public.app_is_admin())',
      table_name || '_admin_delete_scope',
      table_name
    );
  END LOOP;
END $$;

COMMIT;
