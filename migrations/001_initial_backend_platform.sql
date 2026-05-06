-- CareAgent backend platform schema.
-- Target: PostgreSQL 15+ with optional TimescaleDB replacement for the
-- partitioned observations table.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE app_role AS ENUM ('patient', 'caretaker', 'doctor', 'nurse', 'admin');
CREATE TYPE account_status AS ENUM ('pending', 'active', 'disabled', 'deleted');
CREATE TYPE auth_provider AS ENUM ('firebase', 'auth0', 'cognito', 'internal_test');
CREATE TYPE care_team_role AS ENUM ('family', 'caretaker', 'nurse', 'doctor', 'ambulance', 'hospital', 'other');
CREATE TYPE grant_status AS ENUM ('active', 'revoked', 'expired');
CREATE TYPE consent_status AS ENUM ('active', 'revoked', 'expired');
CREATE TYPE consent_event_type AS ENUM ('granted', 'updated', 'revoked', 'expired');
CREATE TYPE contact_channel AS ENUM ('push', 'in_app', 'whatsapp', 'telegram', 'sms', 'voice', 'email');
CREATE TYPE verification_status AS ENUM ('unverified', 'pending', 'verified', 'failed');
CREATE TYPE source_type AS ENUM ('healthkit', 'health_connect', 'ble', 'vendor_api', 'fhir', 'ocr', 'manual', 'simulator');
CREATE TYPE reliability_tier AS ENUM ('clinical', 'os_aggregator', 'standard_ble', 'vendor_api', 'manual_or_ocr', 'unknown');
CREATE TYPE document_status AS ENUM ('queued', 'running', 'blocked', 'completed', 'failed', 'cancelled');
CREATE TYPE malware_scan_status AS ENUM ('pending', 'clean', 'infected', 'failed', 'quarantined');
CREATE TYPE review_status AS ENUM ('pending', 'approved', 'corrected', 'rejected');
CREATE TYPE dose_event_status AS ENUM ('due', 'taken', 'skipped', 'missed', 'snoozed');
CREATE TYPE risk_severity AS ENUM ('informational', 'low', 'moderate', 'high', 'critical');
CREATE TYPE risk_event_status AS ENUM ('open', 'acknowledged', 'escalating', 'resolved', 'false_positive', 'cancelled');
CREATE TYPE alert_status AS ENUM ('open', 'acknowledged', 'resolved', 'suppressed', 'expired');
CREATE TYPE escalation_run_status AS ENUM ('pending', 'running', 'awaiting_ack', 'acknowledged', 'completed', 'failed', 'cancelled');
CREATE TYPE escalation_action_status AS ENUM ('pending', 'attempting', 'sent', 'delivered', 'answered', 'acknowledged', 'failed', 'skipped', 'cancelled');
CREATE TYPE actor_type AS ENUM ('user', 'system', 'agent', 'provider_webhook', 'background_worker');
CREATE TYPE audit_outcome AS ENUM ('success', 'denied', 'error');
CREATE TYPE tool_call_status AS ENUM ('requested', 'authorized', 'denied', 'succeeded', 'failed');
CREATE TYPE event_status AS ENUM ('pending', 'published', 'failed', 'dead_lettered');
CREATE TYPE idempotency_status AS ENUM ('in_progress', 'completed', 'failed');

CREATE TABLE user_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email citext UNIQUE,
  phone text UNIQUE,
  display_name text,
  role app_role NOT NULL,
  status account_status NOT NULL DEFAULT 'pending',
  mfa_required boolean NOT NULL DEFAULT false,
  locale text NOT NULL DEFAULT 'en-IN',
  timezone text NOT NULL DEFAULT 'Asia/Kolkata',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE TABLE auth_identities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_account_id uuid NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
  provider auth_provider NOT NULL,
  provider_subject text NOT NULL,
  provider_claims jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_login_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_subject),
  UNIQUE (user_account_id, provider)
);

CREATE TABLE patient_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL UNIQUE REFERENCES user_accounts(id) ON DELETE RESTRICT,
  full_name text NOT NULL,
  date_of_birth date,
  sex text,
  primary_language text NOT NULL DEFAULT 'en',
  address jsonb NOT NULL DEFAULT '{}'::jsonb,
  emergency_location_notes text,
  conditions jsonb NOT NULL DEFAULT '[]'::jsonb,
  allergies jsonb NOT NULL DEFAULT '[]'::jsonb,
  baseline_notes text,
  primary_doctor_contact_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE contact_endpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL,
  relationship text,
  phone text,
  whatsapp_id text,
  telegram_id text,
  email citext,
  preferred_channel contact_channel,
  verified_status verification_status NOT NULL DEFAULT 'unverified',
  quiet_hours jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    phone IS NOT NULL OR whatsapp_id IS NOT NULL OR telegram_id IS NOT NULL OR email IS NOT NULL
  )
);

ALTER TABLE patient_profiles
  ADD CONSTRAINT patient_profiles_primary_doctor_contact_fk
  FOREIGN KEY (primary_doctor_contact_id) REFERENCES contact_endpoints(id) ON DELETE SET NULL;

CREATE TABLE care_team_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  user_account_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  contact_id uuid REFERENCES contact_endpoints(id) ON DELETE SET NULL,
  role care_team_role NOT NULL,
  priority_order integer NOT NULL DEFAULT 100,
  permissions jsonb NOT NULL DEFAULT '{}'::jsonb,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (user_account_id IS NOT NULL OR contact_id IS NOT NULL)
);

CREATE INDEX care_team_members_patient_idx ON care_team_members(patient_id, active, priority_order);
CREATE UNIQUE INDEX care_team_members_patient_user_active_idx
  ON care_team_members(patient_id, user_account_id)
  WHERE active = true AND user_account_id IS NOT NULL;

CREATE TABLE patient_access_grants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  grantee_user_account_id uuid NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
  granted_by_user_account_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  care_team_member_id uuid REFERENCES care_team_members(id) ON DELETE SET NULL,
  role app_role NOT NULL,
  permissions text[] NOT NULL DEFAULT ARRAY[]::text[],
  status grant_status NOT NULL DEFAULT 'active',
  starts_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (role <> 'patient')
);

CREATE INDEX patient_access_grants_grantee_idx
  ON patient_access_grants(grantee_user_account_id, status, patient_id);
CREATE UNIQUE INDEX patient_access_grants_active_unique_idx
  ON patient_access_grants(patient_id, grantee_user_account_id)
  WHERE status = 'active';

CREATE TABLE consent_grants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  subject_user_id uuid NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
  consent_type text NOT NULL,
  scope jsonb NOT NULL DEFAULT '{}'::jsonb,
  channel contact_channel,
  granted_to_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  granted_to_contact_id uuid REFERENCES contact_endpoints(id) ON DELETE SET NULL,
  status consent_status NOT NULL DEFAULT 'active',
  granted_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  revoked_at timestamptz,
  consent_text_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX consent_grants_patient_type_idx
  ON consent_grants(patient_id, consent_type, status);
CREATE INDEX consent_grants_granted_to_user_idx
  ON consent_grants(granted_to_user_id, status)
  WHERE granted_to_user_id IS NOT NULL;

CREATE TABLE consent_ledger (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  consent_grant_id uuid REFERENCES consent_grants(id) ON DELETE SET NULL,
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  subject_user_id uuid NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
  actor_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  event_type consent_event_type NOT NULL,
  consent_type text NOT NULL,
  scope jsonb NOT NULL DEFAULT '{}'::jsonb,
  channel contact_channel,
  granted_to_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  granted_to_contact_id uuid REFERENCES contact_endpoints(id) ON DELETE SET NULL,
  status_after consent_status NOT NULL,
  effective_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  consent_text_version text NOT NULL,
  reason text,
  request_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX consent_ledger_patient_type_idx
  ON consent_ledger(patient_id, consent_type, created_at DESC);

CREATE TABLE device_catalog (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  brand text NOT NULL,
  model text NOT NULL,
  category text NOT NULL,
  support_tier text NOT NULL,
  connection_methods text[] NOT NULL DEFAULT ARRAY[]::text[],
  supported_metrics text[] NOT NULL DEFAULT ARRAY[]::text[],
  validation_status text NOT NULL DEFAULT 'unvalidated',
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (brand, model)
);

CREATE TABLE devices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  catalog_device_id uuid REFERENCES device_catalog(id) ON DELETE SET NULL,
  display_name text NOT NULL,
  brand text,
  model text,
  category text NOT NULL,
  connection_method text NOT NULL,
  supported_metrics text[] NOT NULL DEFAULT ARRAY[]::text[],
  reliability_tier reliability_tier NOT NULL DEFAULT 'unknown',
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX devices_patient_idx ON devices(patient_id, active, category);

CREATE TABLE device_connections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  platform text NOT NULL,
  external_account_id text,
  status text NOT NULL DEFAULT 'pending',
  last_sync_at timestamptz,
  last_seen_at timestamptz,
  battery_level numeric(5,2),
  error_code text,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (battery_level IS NULL OR (battery_level >= 0 AND battery_level <= 100))
);

CREATE INDEX device_connections_device_idx ON device_connections(device_id, status, last_seen_at DESC);

CREATE TABLE observation_raw_payloads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  device_id uuid REFERENCES devices(id) ON DELETE SET NULL,
  source_type source_type NOT NULL,
  payload_json jsonb,
  object_uri text,
  payload_sha256 text,
  received_at timestamptz NOT NULL DEFAULT now(),
  CHECK (payload_json IS NOT NULL OR object_uri IS NOT NULL)
);

CREATE INDEX observation_raw_payloads_patient_idx
  ON observation_raw_payloads(patient_id, received_at DESC);

CREATE TABLE observations (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  device_id uuid REFERENCES devices(id) ON DELETE SET NULL,
  metric_code text NOT NULL,
  value_numeric numeric,
  value_text text,
  unit text,
  observed_at timestamptz NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  source_type source_type NOT NULL,
  reliability_tier reliability_tier NOT NULL DEFAULT 'unknown',
  confidence numeric(5,4) NOT NULL DEFAULT 1.0,
  raw_payload_id uuid REFERENCES observation_raw_payloads(id) ON DELETE SET NULL,
  abnormal_flag text,
  trend_flag text,
  fhir_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  PRIMARY KEY (id, observed_at),
  CHECK (confidence >= 0 AND confidence <= 1),
  CHECK (value_numeric IS NOT NULL OR value_text IS NOT NULL)
) PARTITION BY RANGE (observed_at);

CREATE TABLE observations_default PARTITION OF observations DEFAULT;

CREATE INDEX observations_default_patient_metric_observed_idx
  ON observations_default(patient_id, metric_code, observed_at DESC);
CREATE INDEX observations_default_observed_brin_idx
  ON observations_default USING brin(observed_at);

CREATE TABLE medicines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  name text NOT NULL,
  normalized_name text,
  strength text,
  form text,
  instructions text,
  source_document_id uuid,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX medicines_patient_idx ON medicines(patient_id, active, name);

CREATE TABLE medicine_schedules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  medicine_id uuid NOT NULL REFERENCES medicines(id) ON DELETE CASCADE,
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  dose text NOT NULL,
  route text,
  scheduled_times jsonb NOT NULL,
  start_date date NOT NULL,
  end_date date,
  with_food text,
  special_instructions text,
  review_status review_status NOT NULL DEFAULT 'pending',
  created_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX medicine_schedules_patient_idx
  ON medicine_schedules(patient_id, review_status, start_date, end_date);

CREATE TABLE medicine_dose_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  schedule_id uuid NOT NULL REFERENCES medicine_schedules(id) ON DELETE CASCADE,
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  scheduled_at timestamptz NOT NULL,
  status dose_event_status NOT NULL,
  recorded_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  source_channel contact_channel,
  idempotency_key text,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (patient_id, schedule_id, scheduled_at, status, idempotency_key)
);

CREATE INDEX medicine_dose_events_patient_schedule_idx
  ON medicine_dose_events(patient_id, scheduled_at DESC, status);

CREATE TABLE medical_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  uploaded_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  upload_channel contact_channel NOT NULL DEFAULT 'in_app',
  object_bucket text NOT NULL,
  object_key text NOT NULL,
  file_uri text NOT NULL,
  file_type text NOT NULL,
  document_type text,
  original_filename text NOT NULL,
  file_size_bytes bigint NOT NULL,
  sha256 text NOT NULL,
  malware_scan_status malware_scan_status NOT NULL DEFAULT 'pending',
  malware_scan_completed_at timestamptz,
  malware_scan_provider text,
  access_policy jsonb NOT NULL DEFAULT '{"classification":"phi","raw_access":"deny_until_clean"}'::jsonb,
  ocr_status document_status NOT NULL DEFAULT 'queued',
  extraction_status document_status NOT NULL DEFAULT 'queued',
  review_status review_status NOT NULL DEFAULT 'pending',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (object_bucket, object_key),
  UNIQUE (patient_id, sha256)
);

ALTER TABLE medicines
  ADD CONSTRAINT medicines_source_document_fk
  FOREIGN KEY (source_document_id) REFERENCES medical_documents(id) ON DELETE SET NULL;

CREATE INDEX medical_documents_patient_idx
  ON medical_documents(patient_id, created_at DESC);
CREATE INDEX medical_documents_processing_idx
  ON medical_documents(malware_scan_status, ocr_status, extraction_status);

CREATE TABLE document_processing_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES medical_documents(id) ON DELETE CASCADE,
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  stage text NOT NULL,
  status document_status NOT NULL,
  provider text,
  started_at timestamptz,
  completed_at timestamptz,
  error_code text,
  error_message text,
  output_ref text,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX document_processing_runs_document_idx
  ON document_processing_runs(document_id, created_at DESC);

CREATE TABLE extracted_medical_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES medical_documents(id) ON DELETE CASCADE,
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  fact_type text NOT NULL,
  label text NOT NULL,
  value text NOT NULL,
  unit text,
  effective_date date,
  confidence numeric(5,4) NOT NULL,
  source_page integer,
  source_text_span jsonb,
  review_status review_status NOT NULL DEFAULT 'pending',
  corrected_value text,
  corrected_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  corrected_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX extracted_medical_facts_patient_type_idx
  ON extracted_medical_facts(patient_id, fact_type, effective_date DESC);

CREATE TABLE risk_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_key text NOT NULL,
  version integer NOT NULL,
  name text NOT NULL,
  severity risk_severity NOT NULL,
  metric_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
  conditions jsonb NOT NULL DEFAULT '{}'::jsonb,
  required_reliability reliability_tier[] NOT NULL DEFAULT ARRAY[]::reliability_tier[],
  rationale text NOT NULL,
  reviewer text,
  approved_at timestamptz,
  active boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rule_key, version)
);

CREATE TABLE risk_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  severity risk_severity NOT NULL,
  confidence numeric(5,4) NOT NULL,
  reason text NOT NULL,
  evidence_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  status risk_event_status NOT NULL DEFAULT 'open',
  detected_at timestamptz NOT NULL DEFAULT now(),
  acknowledged_at timestamptz,
  acknowledged_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  resolved_at timestamptz,
  rule_id uuid REFERENCES risk_rules(id) ON DELETE SET NULL,
  idempotency_key text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX risk_events_patient_status_idx
  ON risk_events(patient_id, status, severity, detected_at DESC);
CREATE UNIQUE INDEX risk_events_idempotency_idx
  ON risk_events(patient_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE TABLE alerts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  risk_event_id uuid REFERENCES risk_events(id) ON DELETE SET NULL,
  severity risk_severity NOT NULL,
  title text NOT NULL,
  body text NOT NULL,
  status alert_status NOT NULL DEFAULT 'open',
  assigned_to uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  created_by actor_type NOT NULL DEFAULT 'system',
  acknowledged_at timestamptz,
  acknowledged_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  resolved_at timestamptz,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX alerts_patient_status_idx
  ON alerts(patient_id, status, severity, created_at DESC);

CREATE TABLE escalation_policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  name text NOT NULL,
  severity_trigger risk_severity NOT NULL,
  patient_confirmation_timeout_seconds integer NOT NULL DEFAULT 120,
  emergency_enabled boolean NOT NULL DEFAULT false,
  location_sharing_enabled boolean NOT NULL DEFAULT false,
  simulation_mode boolean NOT NULL DEFAULT true,
  active boolean NOT NULL DEFAULT true,
  created_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (patient_confirmation_timeout_seconds >= 0)
);

CREATE INDEX escalation_policies_patient_idx
  ON escalation_policies(patient_id, active, severity_trigger);

CREATE TABLE escalation_policy_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_id uuid NOT NULL REFERENCES escalation_policies(id) ON DELETE CASCADE,
  step_order integer NOT NULL,
  action_type text NOT NULL,
  target_contact_id uuid REFERENCES contact_endpoints(id) ON DELETE SET NULL,
  target_role care_team_role,
  channel contact_channel NOT NULL,
  template_id text,
  timeout_seconds integer NOT NULL DEFAULT 60,
  retry_count integer NOT NULL DEFAULT 0,
  retry_delay_seconds integer NOT NULL DEFAULT 30,
  include_location boolean NOT NULL DEFAULT false,
  enabled boolean NOT NULL DEFAULT true,
  payload_template jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (policy_id, step_order),
  CHECK (timeout_seconds >= 0 AND retry_count >= 0 AND retry_delay_seconds >= 0),
  CHECK (target_contact_id IS NOT NULL OR target_role IS NOT NULL)
);

CREATE TABLE escalation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  risk_event_id uuid NOT NULL REFERENCES risk_events(id) ON DELETE CASCADE,
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  policy_id uuid NOT NULL REFERENCES escalation_policies(id) ON DELETE RESTRICT,
  status escalation_run_status NOT NULL DEFAULT 'pending',
  idempotency_key text NOT NULL,
  requested_by actor_type NOT NULL,
  requested_by_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  outcome text,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (risk_event_id, policy_id),
  UNIQUE (idempotency_key)
);

CREATE INDEX escalation_runs_patient_status_idx
  ON escalation_runs(patient_id, status, started_at DESC);

CREATE TABLE escalation_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  escalation_run_id uuid NOT NULL REFERENCES escalation_runs(id) ON DELETE CASCADE,
  step_id uuid REFERENCES escalation_policy_steps(id) ON DELETE SET NULL,
  step_order integer NOT NULL,
  attempt_number integer NOT NULL DEFAULT 1,
  action_type text NOT NULL,
  target_contact_id uuid REFERENCES contact_endpoints(id) ON DELETE SET NULL,
  channel contact_channel NOT NULL,
  template_id text,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  status escalation_action_status NOT NULL DEFAULT 'pending',
  attempted_at timestamptz,
  completed_at timestamptz,
  provider_message_id text,
  provider_call_id text,
  provider_status text,
  error_code text,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (escalation_run_id, step_order, attempt_number)
);

CREATE INDEX escalation_actions_run_idx
  ON escalation_actions(escalation_run_id, step_order, attempt_number);

CREATE TABLE conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  channel contact_channel NOT NULL,
  external_thread_id text,
  started_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX conversations_patient_idx
  ON conversations(patient_id, channel, updated_at DESC);

CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  sender_type actor_type NOT NULL,
  sender_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  channel contact_channel NOT NULL,
  direction text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
  body text,
  media_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  provider_message_id text,
  delivery_status text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX messages_conversation_idx
  ON messages(conversation_id, created_at DESC);

CREATE TABLE agent_tool_calls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
  message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
  tool_name text NOT NULL,
  actor_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  model_name text,
  runtime_name text,
  request_id text NOT NULL,
  authorization_scope text NOT NULL,
  reason text NOT NULL,
  input_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  output_json jsonb,
  policy_decision jsonb NOT NULL DEFAULT '{}'::jsonb,
  status tool_call_status NOT NULL DEFAULT 'requested',
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  audit_log_id uuid,
  error_code text,
  error_message text
);

CREATE INDEX agent_tool_calls_patient_idx
  ON agent_tool_calls(patient_id, started_at DESC);
CREATE INDEX agent_tool_calls_request_idx ON agent_tool_calls(request_id);

CREATE TABLE idempotency_keys (
  key text PRIMARY KEY,
  patient_id uuid REFERENCES patient_profiles(id) ON DELETE CASCADE,
  route text NOT NULL,
  request_hash text NOT NULL,
  status idempotency_status NOT NULL DEFAULT 'in_progress',
  response_status integer,
  response_body jsonb,
  locked_until timestamptz NOT NULL DEFAULT now() + interval '5 minutes',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idempotency_keys_patient_route_idx
  ON idempotency_keys(patient_id, route, created_at DESC);

CREATE TABLE outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  topic text NOT NULL,
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  patient_id uuid REFERENCES patient_profiles(id) ON DELETE CASCADE,
  event_key text,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  status event_status NOT NULL DEFAULT 'pending',
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX outbox_events_pending_idx
  ON outbox_events(status, next_attempt_at, created_at);
CREATE UNIQUE INDEX outbox_events_event_key_idx
  ON outbox_events(event_key)
  WHERE event_key IS NOT NULL;

CREATE TABLE audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_type actor_type NOT NULL,
  actor_id text,
  actor_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  patient_id uuid REFERENCES patient_profiles(id) ON DELETE SET NULL,
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text,
  outcome audit_outcome NOT NULL DEFAULT 'success',
  phi_access boolean NOT NULL DEFAULT false,
  reason text,
  request_id text,
  ip_address inet,
  user_agent text,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  previous_hash text,
  entry_hash text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_logs_patient_created_idx
  ON audit_logs(patient_id, created_at DESC);
CREATE INDEX audit_logs_actor_created_idx
  ON audit_logs(actor_user_id, created_at DESC)
  WHERE actor_user_id IS NOT NULL;
CREATE INDEX audit_logs_action_created_idx
  ON audit_logs(action, created_at DESC);

ALTER TABLE agent_tool_calls
  ADD CONSTRAINT agent_tool_calls_audit_log_fk
  FOREIGN KEY (audit_log_id) REFERENCES audit_logs(id) ON DELETE SET NULL;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER user_accounts_set_updated_at BEFORE UPDATE ON user_accounts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER auth_identities_set_updated_at BEFORE UPDATE ON auth_identities
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER patient_profiles_set_updated_at BEFORE UPDATE ON patient_profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER contact_endpoints_set_updated_at BEFORE UPDATE ON contact_endpoints
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER care_team_members_set_updated_at BEFORE UPDATE ON care_team_members
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER patient_access_grants_set_updated_at BEFORE UPDATE ON patient_access_grants
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER consent_grants_set_updated_at BEFORE UPDATE ON consent_grants
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER device_catalog_set_updated_at BEFORE UPDATE ON device_catalog
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER devices_set_updated_at BEFORE UPDATE ON devices
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER device_connections_set_updated_at BEFORE UPDATE ON device_connections
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER medicines_set_updated_at BEFORE UPDATE ON medicines
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER medicine_schedules_set_updated_at BEFORE UPDATE ON medicine_schedules
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER medical_documents_set_updated_at BEFORE UPDATE ON medical_documents
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER extracted_medical_facts_set_updated_at BEFORE UPDATE ON extracted_medical_facts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER risk_rules_set_updated_at BEFORE UPDATE ON risk_rules
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER risk_events_set_updated_at BEFORE UPDATE ON risk_events
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER alerts_set_updated_at BEFORE UPDATE ON alerts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER escalation_policies_set_updated_at BEFORE UPDATE ON escalation_policies
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER escalation_policy_steps_set_updated_at BEFORE UPDATE ON escalation_policy_steps
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER escalation_runs_set_updated_at BEFORE UPDATE ON escalation_runs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER escalation_actions_set_updated_at BEFORE UPDATE ON escalation_actions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER conversations_set_updated_at BEFORE UPDATE ON conversations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER idempotency_keys_set_updated_at BEFORE UPDATE ON idempotency_keys
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER outbox_events_set_updated_at BEFORE UPDATE ON outbox_events
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION app_current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT nullif(current_setting('app.user_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION app_current_role()
RETURNS app_role
LANGUAGE sql
STABLE
AS $$
  SELECT nullif(current_setting('app.role', true), '')::app_role;
$$;

CREATE OR REPLACE FUNCTION app_is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM user_accounts ua
    WHERE ua.id = app_current_user_id()
      AND ua.role = 'admin'
      AND ua.status = 'active'
  );
$$;

CREATE OR REPLACE FUNCTION app_can_access_patient(target_patient_id uuid, required_permission text DEFAULT 'patient:read')
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT app_is_admin()
    OR EXISTS (
      SELECT 1
      FROM patient_profiles pp
      WHERE pp.id = target_patient_id
        AND pp.account_id = app_current_user_id()
    )
    OR EXISTS (
      SELECT 1
      FROM patient_access_grants pag
      WHERE pag.patient_id = target_patient_id
        AND pag.grantee_user_account_id = app_current_user_id()
        AND pag.status = 'active'
        AND pag.starts_at <= now()
        AND (pag.expires_at IS NULL OR pag.expires_at > now())
        AND (
          required_permission = ANY(pag.permissions)
          OR 'patient:*' = ANY(pag.permissions)
          OR (
            required_permission LIKE '%:read'
            AND 'patient:read' = ANY(pag.permissions)
          )
        )
    );
$$;

CREATE OR REPLACE FUNCTION protect_audit_log_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs are append-only';
END;
$$;

CREATE TRIGGER audit_logs_no_update BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION protect_audit_log_immutability();

ALTER TABLE patient_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE care_team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE patient_access_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE observation_raw_payloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE medicines ENABLE ROW LEVEL SECURITY;
ALTER TABLE medicine_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE medicine_dose_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE medical_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_processing_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE extracted_medical_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalation_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalation_policy_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalation_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tool_calls ENABLE ROW LEVEL SECURITY;

CREATE POLICY patient_profiles_scope ON patient_profiles
  USING (app_is_admin() OR account_id = app_current_user_id() OR app_can_access_patient(id, 'patient:read'))
  WITH CHECK (app_is_admin() OR account_id = app_current_user_id());

CREATE POLICY care_team_members_scope ON care_team_members
  USING (app_can_access_patient(patient_id, 'care_team:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'care_team:write'));

CREATE POLICY patient_access_grants_scope ON patient_access_grants
  USING (app_is_admin() OR app_can_access_patient(patient_id, 'care_team:read'))
  WITH CHECK (app_is_admin() OR app_can_access_patient(patient_id, 'care_team:write'));

CREATE POLICY consent_grants_scope ON consent_grants
  USING (app_can_access_patient(patient_id, 'consent:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'consent:write'));

CREATE POLICY consent_ledger_scope ON consent_ledger
  USING (app_can_access_patient(patient_id, 'consent:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'consent:write'));

CREATE POLICY devices_scope ON devices
  USING (app_can_access_patient(patient_id, 'devices:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'devices:write'));

CREATE POLICY device_connections_scope ON device_connections
  USING (
    EXISTS (
      SELECT 1 FROM devices d
      WHERE d.id = device_id
        AND app_can_access_patient(d.patient_id, 'devices:read')
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM devices d
      WHERE d.id = device_id
        AND app_can_access_patient(d.patient_id, 'devices:write')
    )
  );

CREATE POLICY patient_scoped_read_write ON observation_raw_payloads
  USING (app_can_access_patient(patient_id, 'observations:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'observations:write'));

CREATE POLICY observations_scope ON observations
  USING (app_can_access_patient(patient_id, 'observations:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'observations:write'));

CREATE POLICY medicines_scope ON medicines
  USING (app_can_access_patient(patient_id, 'medicines:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'medicines:write'));

CREATE POLICY medicine_schedules_scope ON medicine_schedules
  USING (app_can_access_patient(patient_id, 'medicines:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'medicines:write'));

CREATE POLICY medicine_dose_events_scope ON medicine_dose_events
  USING (app_can_access_patient(patient_id, 'medicines:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'medicines:write'));

CREATE POLICY medical_documents_scope ON medical_documents
  USING (app_can_access_patient(patient_id, 'documents:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'documents:write'));

CREATE POLICY document_processing_runs_scope ON document_processing_runs
  USING (app_can_access_patient(patient_id, 'documents:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'documents:write'));

CREATE POLICY extracted_medical_facts_scope ON extracted_medical_facts
  USING (app_can_access_patient(patient_id, 'documents:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'documents:write'));

CREATE POLICY risk_events_scope ON risk_events
  USING (app_can_access_patient(patient_id, 'risk:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'risk:write'));

CREATE POLICY alerts_scope ON alerts
  USING (app_can_access_patient(patient_id, 'alerts:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'alerts:write'));

CREATE POLICY escalation_policies_scope ON escalation_policies
  USING (app_can_access_patient(patient_id, 'escalation:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'escalation:write'));

CREATE POLICY escalation_policy_steps_scope ON escalation_policy_steps
  USING (
    EXISTS (
      SELECT 1 FROM escalation_policies ep
      WHERE ep.id = policy_id
        AND app_can_access_patient(ep.patient_id, 'escalation:read')
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM escalation_policies ep
      WHERE ep.id = policy_id
        AND app_can_access_patient(ep.patient_id, 'escalation:write')
    )
  );

CREATE POLICY escalation_runs_scope ON escalation_runs
  USING (app_can_access_patient(patient_id, 'escalation:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'escalation:write'));

CREATE POLICY escalation_actions_scope ON escalation_actions
  USING (
    EXISTS (
      SELECT 1 FROM escalation_runs er
      WHERE er.id = escalation_run_id
        AND app_can_access_patient(er.patient_id, 'escalation:read')
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM escalation_runs er
      WHERE er.id = escalation_run_id
        AND app_can_access_patient(er.patient_id, 'escalation:write')
    )
  );

CREATE POLICY conversations_scope ON conversations
  USING (app_can_access_patient(patient_id, 'agent:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'agent:write'));

CREATE POLICY messages_scope ON messages
  USING (app_can_access_patient(patient_id, 'agent:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'agent:write'));

CREATE POLICY agent_tool_calls_scope ON agent_tool_calls
  USING (app_can_access_patient(patient_id, 'agent:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'agent:write'));

COMMIT;
