-- Add Supabase Auth as a first-class identity provider.
--
-- This is separated from the auth bridge migration because PostgreSQL enum
-- values cannot be used safely inside the same migration transaction that
-- creates them.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_enum e
    JOIN pg_type t ON t.oid = e.enumtypid
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public'
      AND t.typname = 'auth_provider'
      AND e.enumlabel = 'supabase'
  ) THEN
    ALTER TYPE public.auth_provider ADD VALUE 'supabase';
  END IF;
END
$$;
