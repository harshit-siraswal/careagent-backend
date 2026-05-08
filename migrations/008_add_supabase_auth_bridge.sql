-- Bridge Supabase Auth users into CareAgent account tables.
--
-- The mobile app authenticates through Supabase Auth. CareAgent keeps role,
-- patient access, consent, and PHI authorization in backend-owned tables.
-- This bridge creates/updates the corresponding user account and auth identity
-- rows when Supabase Auth users are inserted or updated.

CREATE OR REPLACE FUNCTION public.app_current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
SET search_path TO 'public', 'auth', 'extensions'
AS $function$
  SELECT COALESCE(
    nullif(current_setting('app.user_id', true), '')::uuid,
    auth.uid()
  );
$function$;

CREATE OR REPLACE FUNCTION public.app_current_role()
RETURNS public.app_role
LANGUAGE sql
STABLE
SET search_path TO 'public', 'auth', 'extensions'
AS $function$
  SELECT COALESCE(
    nullif(current_setting('app.role', true), '')::public.app_role,
    nullif(auth.jwt() -> 'app_metadata' ->> 'role', '')::public.app_role,
    'patient'::public.app_role
  );
$function$;

CREATE OR REPLACE FUNCTION private.sync_supabase_auth_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'auth', 'extensions'
AS $function$
DECLARE
  resolved_role public.app_role := 'patient'::public.app_role;
  resolved_name text;
BEGIN
  IF NEW.raw_app_meta_data ? 'role'
     AND NEW.raw_app_meta_data ->> 'role' IN (
       'patient',
       'caretaker',
       'doctor',
       'nurse',
       'admin'
     ) THEN
    resolved_role := (NEW.raw_app_meta_data ->> 'role')::public.app_role;
  END IF;

  resolved_name := COALESCE(
    nullif(NEW.raw_user_meta_data ->> 'full_name', ''),
    nullif(NEW.raw_user_meta_data ->> 'name', ''),
    nullif(NEW.email, ''),
    nullif(NEW.phone, '')
  );

  INSERT INTO public.user_accounts (
    id,
    email,
    phone,
    display_name,
    role,
    status,
    locale,
    timezone
  ) VALUES (
    NEW.id,
    NEW.email::citext,
    NEW.phone,
    resolved_name,
    resolved_role,
    'active'::public.account_status,
    COALESCE(nullif(NEW.raw_app_meta_data ->> 'locale', ''), 'en-IN'),
    COALESCE(nullif(NEW.raw_app_meta_data ->> 'timezone', ''), 'Asia/Kolkata')
  )
  ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    phone = EXCLUDED.phone,
    display_name = COALESCE(EXCLUDED.display_name, public.user_accounts.display_name),
    role = CASE
      WHEN public.user_accounts.role = 'admin'::public.app_role THEN public.user_accounts.role
      ELSE EXCLUDED.role
    END,
    status = CASE
      WHEN public.user_accounts.status = 'deleted'::public.account_status THEN public.user_accounts.status
      ELSE 'active'::public.account_status
    END,
    locale = EXCLUDED.locale,
    timezone = EXCLUDED.timezone,
    updated_at = now();

  INSERT INTO public.auth_identities (
    user_account_id,
    provider,
    provider_subject,
    provider_claims,
    last_login_at
  ) VALUES (
    NEW.id,
    'supabase'::public.auth_provider,
    NEW.id::text,
    jsonb_build_object(
      'issuer', 'supabase_auth',
      'auth_provider', COALESCE(NEW.raw_app_meta_data ->> 'provider', 'unknown'),
      'providers', COALESCE(NEW.raw_app_meta_data -> 'providers', '[]'::jsonb)
    ),
    NEW.last_sign_in_at
  )
  ON CONFLICT (user_account_id, provider) DO UPDATE SET
    provider_subject = EXCLUDED.provider_subject,
    provider_claims = EXCLUDED.provider_claims,
    last_login_at = EXCLUDED.last_login_at,
    updated_at = now();

  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS on_auth_user_sync_careagent_account ON auth.users;

CREATE TRIGGER on_auth_user_sync_careagent_account
AFTER INSERT OR UPDATE OF
  email,
  phone,
  raw_app_meta_data,
  raw_user_meta_data,
  last_sign_in_at
ON auth.users
FOR EACH ROW
EXECUTE FUNCTION private.sync_supabase_auth_user();

INSERT INTO public.user_accounts (
  id,
  email,
  phone,
  display_name,
  role,
  status,
  locale,
  timezone
)
SELECT
  u.id,
  u.email::citext,
  u.phone,
  COALESCE(
    nullif(u.raw_user_meta_data ->> 'full_name', ''),
    nullif(u.raw_user_meta_data ->> 'name', ''),
    nullif(u.email, ''),
    nullif(u.phone, '')
  ),
  CASE
    WHEN u.raw_app_meta_data ? 'role'
      AND u.raw_app_meta_data ->> 'role' IN (
        'patient',
        'caretaker',
        'doctor',
        'nurse',
        'admin'
      )
      THEN (u.raw_app_meta_data ->> 'role')::public.app_role
    ELSE 'patient'::public.app_role
  END,
  'active'::public.account_status,
  COALESCE(nullif(u.raw_app_meta_data ->> 'locale', ''), 'en-IN'),
  COALESCE(nullif(u.raw_app_meta_data ->> 'timezone', ''), 'Asia/Kolkata')
FROM auth.users u
ON CONFLICT (id) DO UPDATE SET
  email = EXCLUDED.email,
  phone = EXCLUDED.phone,
  display_name = COALESCE(EXCLUDED.display_name, public.user_accounts.display_name),
  role = CASE
    WHEN public.user_accounts.role = 'admin'::public.app_role THEN public.user_accounts.role
    ELSE EXCLUDED.role
  END,
  status = CASE
    WHEN public.user_accounts.status = 'deleted'::public.account_status THEN public.user_accounts.status
    ELSE 'active'::public.account_status
  END,
  locale = EXCLUDED.locale,
  timezone = EXCLUDED.timezone,
  updated_at = now();

INSERT INTO public.auth_identities (
  user_account_id,
  provider,
  provider_subject,
  provider_claims,
  last_login_at
)
SELECT
  u.id,
  'supabase'::public.auth_provider,
  u.id::text,
  jsonb_build_object(
    'issuer', 'supabase_auth',
    'auth_provider', COALESCE(u.raw_app_meta_data ->> 'provider', 'unknown'),
    'providers', COALESCE(u.raw_app_meta_data -> 'providers', '[]'::jsonb)
  ),
  u.last_sign_in_at
FROM auth.users u
ON CONFLICT (user_account_id, provider) DO UPDATE SET
  provider_subject = EXCLUDED.provider_subject,
  provider_claims = EXCLUDED.provider_claims,
  last_login_at = EXCLUDED.last_login_at,
  updated_at = now();
