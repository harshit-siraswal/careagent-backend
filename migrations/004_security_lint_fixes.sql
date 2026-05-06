-- Supabase security advisor fixes after the initial schema rollout.

BEGIN;

CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC;

ALTER FUNCTION public.set_updated_at()
  SET search_path = public, extensions;
ALTER FUNCTION public.app_current_user_id()
  SET search_path = public, extensions;
ALTER FUNCTION public.app_current_role()
  SET search_path = public, extensions;
ALTER FUNCTION public.app_is_admin()
  SET search_path = public, extensions;
ALTER FUNCTION public.protect_audit_log_immutability()
  SET search_path = public, extensions;

ALTER FUNCTION public.app_can_access_patient(uuid, text)
  SET search_path = public, private, extensions;
ALTER FUNCTION public.app_can_access_patient(uuid, text)
  SET SCHEMA private;

COMMENT ON FUNCTION private.app_can_access_patient(uuid, text) IS
  'Patient-scope helper for RLS policies. SECURITY DEFINER is kept in the private schema so it is not exposed as a public RPC.';

ALTER EXTENSION citext SET SCHEMA extensions;

COMMIT;
