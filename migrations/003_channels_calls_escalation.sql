-- CareAgent channels, calls, and escalation execution schema extensions.
-- Extends 001_initial_backend_platform.sql with provider abstraction,
-- template/script registries, delivery receipts, call events, acknowledgements,
-- and emergency simulation tracking.

BEGIN;

CREATE TYPE channel_provider_kind AS ENUM (
  'whatsapp_cloud',
  'whatsapp_bsp',
  'prototype_whatsapp_web',
  'telegram_bot',
  'fcm',
  'apns',
  'sms_gateway',
  'voice_twilio',
  'voice_exotel',
  'voice_plivo',
  'email_smtp',
  'mock_simulator'
);

CREATE TYPE provider_environment AS ENUM ('production', 'sandbox', 'simulation', 'prototype');

CREATE TYPE message_template_status AS ENUM (
  'draft',
  'pending_approval',
  'approved',
  'rejected',
  'disabled'
);

CREATE TYPE call_script_status AS ENUM ('draft', 'approved', 'disabled');

CREATE TYPE dispatch_status AS ENUM (
  'queued',
  'policy_denied',
  'provider_pending',
  'sent',
  'delivered',
  'read',
  'answered',
  'acknowledged',
  'failed',
  'cancelled',
  'expired',
  'simulated'
);

CREATE TYPE escalation_simulation_status AS ENUM (
  'queued',
  'running',
  'passed',
  'failed',
  'cancelled'
);

CREATE TABLE channel_provider_configs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  channel contact_channel NOT NULL,
  provider_kind channel_provider_kind NOT NULL,
  display_name text NOT NULL,
  environment provider_environment NOT NULL,
  prototype_only boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true,
  region_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
  provider_account_ref text,
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
  rate_limits jsonb NOT NULL DEFAULT '{}'::jsonb,
  secret_ref text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (provider_kind <> 'prototype_whatsapp_web' OR prototype_only = true),
  CHECK (environment <> 'production' OR prototype_only = false)
);

CREATE INDEX channel_provider_configs_channel_idx
  ON channel_provider_configs(channel, environment, active);

CREATE TABLE channel_account_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  user_account_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  contact_id uuid REFERENCES contact_endpoints(id) ON DELETE SET NULL,
  provider_config_id uuid NOT NULL REFERENCES channel_provider_configs(id) ON DELETE RESTRICT,
  channel contact_channel NOT NULL,
  external_subject_ref text NOT NULL,
  verification_status verification_status NOT NULL DEFAULT 'unverified',
  verification_method text,
  verification_challenge_hash text,
  verification_expires_at timestamptz,
  verified_at timestamptz,
  commands_enabled boolean NOT NULL DEFAULT false,
  uploads_enabled boolean NOT NULL DEFAULT false,
  last_seen_at timestamptz,
  disabled_at timestamptz,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (user_account_id IS NOT NULL OR contact_id IS NOT NULL),
  UNIQUE (provider_config_id, external_subject_ref)
);

CREATE INDEX channel_account_links_patient_idx
  ON channel_account_links(patient_id, channel, verification_status);
CREATE INDEX channel_account_links_contact_idx
  ON channel_account_links(contact_id, channel)
  WHERE contact_id IS NOT NULL;

CREATE TABLE message_templates (
  id text PRIMARY KEY,
  channel contact_channel NOT NULL,
  category text NOT NULL,
  locale text NOT NULL DEFAULT 'en-IN',
  version integer NOT NULL DEFAULT 1,
  status message_template_status NOT NULL DEFAULT 'draft',
  provider_template_name text,
  provider_template_id text,
  business_initiated boolean NOT NULL DEFAULT false,
  requires_approval boolean NOT NULL DEFAULT false,
  body text NOT NULL,
  variables text[] NOT NULL DEFAULT ARRAY[]::text[],
  interactive_actions jsonb NOT NULL DEFAULT '[]'::jsonb,
  safety_notes text,
  active boolean NOT NULL DEFAULT true,
  created_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (version >= 1),
  CHECK (channel <> 'whatsapp' OR requires_approval = true OR business_initiated = false)
);

CREATE UNIQUE INDEX message_templates_provider_name_idx
  ON message_templates(channel, provider_template_name, locale)
  WHERE provider_template_name IS NOT NULL;

CREATE TABLE call_scripts (
  id text PRIMARY KEY,
  locale text NOT NULL DEFAULT 'en-IN',
  version integer NOT NULL DEFAULT 1,
  status call_script_status NOT NULL DEFAULT 'draft',
  ai_disclosure text NOT NULL,
  opening_text text NOT NULL,
  body_template text NOT NULL,
  dtmf_options jsonb NOT NULL DEFAULT '{}'::jsonb,
  speech_intents jsonb NOT NULL DEFAULT '{}'::jsonb,
  max_duration_seconds integer NOT NULL DEFAULT 120,
  recording_allowed boolean NOT NULL DEFAULT false,
  transcript_allowed boolean NOT NULL DEFAULT false,
  safety_notes text,
  active boolean NOT NULL DEFAULT true,
  created_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (version >= 1),
  CHECK (max_duration_seconds > 0),
  CHECK (position('AI' in ai_disclosure) > 0 OR position('ai' in ai_disclosure) > 0)
);

CREATE TABLE channel_dispatch_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
  message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
  escalation_run_id uuid REFERENCES escalation_runs(id) ON DELETE SET NULL,
  escalation_action_id uuid REFERENCES escalation_actions(id) ON DELETE SET NULL,
  provider_config_id uuid NOT NULL REFERENCES channel_provider_configs(id) ON DELETE RESTRICT,
  channel contact_channel NOT NULL,
  target_contact_id uuid REFERENCES contact_endpoints(id) ON DELETE SET NULL,
  template_id text REFERENCES message_templates(id) ON DELETE SET NULL,
  script_id text REFERENCES call_scripts(id) ON DELETE SET NULL,
  idempotency_key text NOT NULL,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  status dispatch_status NOT NULL DEFAULT 'queued',
  priority integer NOT NULL DEFAULT 100,
  simulation boolean NOT NULL DEFAULT false,
  scheduled_at timestamptz NOT NULL DEFAULT now(),
  attempted_at timestamptz,
  completed_at timestamptz,
  provider_message_id text,
  provider_call_id text,
  provider_status text,
  provider_error_code text,
  error_message text,
  retry_after_seconds integer,
  next_attempt_at timestamptz,
  fallback_from_attempt_id uuid REFERENCES channel_dispatch_attempts(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (idempotency_key),
  CHECK (priority >= 0),
  CHECK (retry_after_seconds IS NULL OR retry_after_seconds >= 0),
  CHECK (channel <> 'voice' OR script_id IS NOT NULL OR template_id IS NOT NULL)
);

CREATE INDEX channel_dispatch_attempts_patient_idx
  ON channel_dispatch_attempts(patient_id, status, scheduled_at DESC);
CREATE INDEX channel_dispatch_attempts_escalation_idx
  ON channel_dispatch_attempts(escalation_run_id, escalation_action_id)
  WHERE escalation_run_id IS NOT NULL;
CREATE INDEX channel_dispatch_attempts_provider_message_idx
  ON channel_dispatch_attempts(provider_config_id, provider_message_id)
  WHERE provider_message_id IS NOT NULL;
CREATE INDEX channel_dispatch_attempts_provider_call_idx
  ON channel_dispatch_attempts(provider_config_id, provider_call_id)
  WHERE provider_call_id IS NOT NULL;

CREATE TABLE delivery_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  dispatch_attempt_id uuid REFERENCES channel_dispatch_attempts(id) ON DELETE SET NULL,
  message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
  escalation_action_id uuid REFERENCES escalation_actions(id) ON DELETE SET NULL,
  provider_config_id uuid NOT NULL REFERENCES channel_provider_configs(id) ON DELETE RESTRICT,
  channel contact_channel NOT NULL,
  event_type text NOT NULL,
  provider_status text NOT NULL,
  provider_event_id text,
  provider_payload_hash text,
  signature_valid boolean NOT NULL DEFAULT false,
  occurred_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX delivery_receipts_patient_idx
  ON delivery_receipts(patient_id, received_at DESC);
CREATE INDEX delivery_receipts_dispatch_idx
  ON delivery_receipts(dispatch_attempt_id, received_at DESC)
  WHERE dispatch_attempt_id IS NOT NULL;
CREATE UNIQUE INDEX delivery_receipts_provider_event_idx
  ON delivery_receipts(provider_config_id, provider_event_id)
  WHERE provider_event_id IS NOT NULL;

CREATE TABLE call_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  dispatch_attempt_id uuid REFERENCES channel_dispatch_attempts(id) ON DELETE SET NULL,
  escalation_action_id uuid REFERENCES escalation_actions(id) ON DELETE SET NULL,
  provider_config_id uuid NOT NULL REFERENCES channel_provider_configs(id) ON DELETE RESTRICT,
  event_type text NOT NULL,
  sequence_number integer NOT NULL DEFAULT 1,
  provider_status text,
  dtmf_digits text,
  speech_intent text,
  redacted_transcript text,
  summary text,
  provider_payload_hash text,
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (sequence_number >= 1)
);

CREATE INDEX call_events_patient_idx
  ON call_events(patient_id, occurred_at DESC);
CREATE INDEX call_events_dispatch_idx
  ON call_events(dispatch_attempt_id, sequence_number)
  WHERE dispatch_attempt_id IS NOT NULL;

CREATE TABLE escalation_acknowledgements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  escalation_run_id uuid NOT NULL REFERENCES escalation_runs(id) ON DELETE CASCADE,
  escalation_action_id uuid REFERENCES escalation_actions(id) ON DELETE SET NULL,
  acknowledged_by_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  acknowledged_by_contact_id uuid REFERENCES contact_endpoints(id) ON DELETE SET NULL,
  provider_config_id uuid REFERENCES channel_provider_configs(id) ON DELETE SET NULL,
  channel contact_channel,
  acknowledgement_method text NOT NULL,
  response_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  acknowledged_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (acknowledged_by_user_id IS NOT NULL OR acknowledged_by_contact_id IS NOT NULL)
);

CREATE INDEX escalation_acknowledgements_run_idx
  ON escalation_acknowledgements(escalation_run_id, acknowledged_at DESC);
CREATE INDEX escalation_acknowledgements_patient_idx
  ON escalation_acknowledgements(patient_id, acknowledged_at DESC);

CREATE TABLE escalation_simulation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  escalation_policy_id uuid NOT NULL REFERENCES escalation_policies(id) ON DELETE RESTRICT,
  risk_event_id uuid REFERENCES risk_events(id) ON DELETE SET NULL,
  escalation_run_id uuid REFERENCES escalation_runs(id) ON DELETE SET NULL,
  scenario_key text NOT NULL,
  status escalation_simulation_status NOT NULL DEFAULT 'queued',
  started_by_user_id uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  expected_steps jsonb NOT NULL DEFAULT '[]'::jsonb,
  actual_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  blocked_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX escalation_simulation_runs_patient_idx
  ON escalation_simulation_runs(patient_id, status, started_at DESC);
CREATE INDEX escalation_simulation_runs_policy_idx
  ON escalation_simulation_runs(escalation_policy_id, scenario_key, started_at DESC);

CREATE TRIGGER channel_provider_configs_set_updated_at BEFORE UPDATE ON channel_provider_configs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER channel_account_links_set_updated_at BEFORE UPDATE ON channel_account_links
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER message_templates_set_updated_at BEFORE UPDATE ON message_templates
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER call_scripts_set_updated_at BEFORE UPDATE ON call_scripts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER channel_dispatch_attempts_set_updated_at BEFORE UPDATE ON channel_dispatch_attempts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER escalation_simulation_runs_set_updated_at BEFORE UPDATE ON escalation_simulation_runs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE channel_provider_configs IS
  'Provider configuration registry. secret_ref points to external secret storage; no provider secrets belong in table rows.';
COMMENT ON TABLE channel_account_links IS
  'PHI/PII-bearing patient channel identity links for messaging and escalation.';
COMMENT ON TABLE message_templates IS
  'Outbound message template registry. Template bodies must not include patient-specific PHI.';
COMMENT ON TABLE call_scripts IS
  'Voice call script registry with mandatory AI disclosure text.';
COMMENT ON TABLE channel_dispatch_attempts IS
  'PHI-bearing outbound dispatch attempts. payload_json must be minimized and redacted where possible.';
COMMENT ON TABLE delivery_receipts IS
  'PHI-bearing provider delivery receipts. Store payload hashes instead of raw provider payloads.';
COMMENT ON TABLE call_events IS
  'PHI-bearing voice event history. Transcript fields must be redacted summaries, not raw recordings.';
COMMENT ON TABLE escalation_acknowledgements IS
  'PHI-bearing human acknowledgement records for emergency escalation review.';
COMMENT ON TABLE escalation_simulation_runs IS
  'Patient-scoped emergency simulation results for safety QA.';

ALTER TABLE channel_provider_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_account_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_scripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_dispatch_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalation_acknowledgements ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalation_simulation_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY channel_provider_configs_admin_scope ON channel_provider_configs
  USING (app_is_admin())
  WITH CHECK (app_is_admin());

CREATE POLICY message_templates_admin_scope ON message_templates
  USING (app_is_admin())
  WITH CHECK (app_is_admin());

CREATE POLICY call_scripts_admin_scope ON call_scripts
  USING (app_is_admin())
  WITH CHECK (app_is_admin());

CREATE POLICY channel_account_links_scope ON channel_account_links
  USING (app_can_access_patient(patient_id, 'agent:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'agent:write'));

CREATE POLICY channel_dispatch_attempts_scope ON channel_dispatch_attempts
  USING (app_can_access_patient(patient_id, 'escalation:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'escalation:write'));

CREATE POLICY delivery_receipts_scope ON delivery_receipts
  USING (app_can_access_patient(patient_id, 'escalation:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'escalation:write'));

CREATE POLICY call_events_scope ON call_events
  USING (app_can_access_patient(patient_id, 'escalation:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'escalation:write'));

CREATE POLICY escalation_acknowledgements_scope ON escalation_acknowledgements
  USING (app_can_access_patient(patient_id, 'escalation:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'escalation:write'));

CREATE POLICY escalation_simulation_runs_scope ON escalation_simulation_runs
  USING (app_can_access_patient(patient_id, 'escalation:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'escalation:write'));

COMMIT;
