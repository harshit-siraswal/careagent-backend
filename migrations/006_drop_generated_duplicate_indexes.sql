-- Remove generated FK indexes if an earlier hand-named index already covers
-- the same columns and predicate.

BEGIN;

DO $$
DECLARE
  duplicate_index record;
BEGIN
  FOR duplicate_index IN
    WITH comparable_indexes AS (
      SELECT
        idx.indexrelid,
        idx.indrelid,
        idx.indkey::text AS indkey,
        idx.indclass::text AS indclass,
        idx.indcollation::text AS indcollation,
        coalesce(pg_get_expr(idx.indexprs, idx.indrelid), '') AS indexprs,
        coalesce(pg_get_expr(idx.indpred, idx.indrelid), '') AS indpred,
        am.amname,
        n.nspname AS schema_name,
        ic.relname AS index_name
      FROM pg_index idx
      JOIN pg_class tc ON tc.oid = idx.indrelid
      JOIN pg_namespace n ON n.oid = tc.relnamespace
      JOIN pg_class ic ON ic.oid = idx.indexrelid
      JOIN pg_am am ON am.oid = ic.relam
      WHERE n.nspname = 'public'
        AND NOT idx.indisprimary
        AND NOT idx.indisunique
    ),
    duplicate_groups AS (
      SELECT
        indrelid,
        indkey,
        indclass,
        indcollation,
        indexprs,
        indpred,
        amname
      FROM comparable_indexes
      GROUP BY indrelid, indkey, indclass, indcollation, indexprs, indpred, amname
      HAVING count(*) > 1
         AND bool_or(index_name LIKE 'idx\_%' ESCAPE '\')
         AND bool_or(index_name NOT LIKE 'idx\_%' ESCAPE '\')
    )
    SELECT format('%I.%I', ci.schema_name, ci.index_name) AS qualified_index_name
    FROM comparable_indexes ci
    JOIN duplicate_groups dg
      ON dg.indrelid = ci.indrelid
     AND dg.indkey = ci.indkey
     AND dg.indclass = ci.indclass
     AND dg.indcollation = ci.indcollation
     AND dg.indexprs = ci.indexprs
     AND dg.indpred = ci.indpred
     AND dg.amname = ci.amname
    WHERE ci.index_name LIKE 'idx\_%' ESCAPE '\'
  LOOP
    EXECUTE format('DROP INDEX IF EXISTS %s', duplicate_index.qualified_index_name);
  END LOOP;
END $$;

COMMIT;
