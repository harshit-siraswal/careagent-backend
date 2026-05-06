-- Health device integration contracts.
-- Depends on 001_initial_backend_platform.sql.

BEGIN;

DO $$
BEGIN
  CREATE TYPE connector_kind AS ENUM (
    'os_health_store',
    'standard_ble',
    'vendor_api',
    'clinical_fhir',
    'manual',
    'ocr',
    'simulator'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE TYPE connector_account_status AS ENUM (
    'pending',
    'active',
    'permission_denied',
    'reauth_required',
    'revoked',
    'failed'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE TYPE connector_sync_status AS ENUM (
    'queued',
    'running',
    'succeeded',
    'partial',
    'failed',
    'cancelled'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE TYPE freshness_status AS ENUM (
    'fresh',
    'delayed',
    'stale',
    'future_timestamp',
    'unknown'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE device_catalog
  ADD COLUMN IF NOT EXISTS supported_platforms text[] NOT NULL DEFAULT ARRAY[]::text[],
  ADD COLUMN IF NOT EXISTS setup_instructions jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS latency_expectation text,
  ADD COLUMN IF NOT EXISTS known_limitations text[] NOT NULL DEFAULT ARRAY[]::text[],
  ADD COLUMN IF NOT EXISTS regulatory_notes text,
  ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS catalog_metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS metric_catalog (
  metric_code text PRIMARY KEY,
  display_name text NOT NULL,
  canonical_unit text NOT NULL,
  accepted_units text[] NOT NULL DEFAULT ARRAY[]::text[],
  value_kind text NOT NULL,
  freshness_warning_after interval NOT NULL,
  freshness_stale_after interval NOT NULL,
  plausible_min numeric,
  plausible_max numeric,
  normal_range_strategy text NOT NULL DEFAULT 'patient_specific',
  fhir_codings jsonb NOT NULL DEFAULT '[]'::jsonb,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (value_kind IN ('numeric', 'boolean', 'text', 'compound', 'attachment')),
  CHECK (freshness_stale_after >= freshness_warning_after)
);

CREATE TABLE IF NOT EXISTS metric_normalization_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type source_type NOT NULL,
  external_metric_code text NOT NULL,
  metric_code text NOT NULL REFERENCES metric_catalog(metric_code) ON DELETE RESTRICT,
  external_unit text,
  canonical_unit text NOT NULL,
  conversion_expression text,
  value_path text,
  timestamp_path text,
  default_reliability_tier reliability_tier NOT NULL DEFAULT 'unknown',
  notes text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS metric_normalization_rules_unique_idx
  ON metric_normalization_rules(source_type, external_metric_code, metric_code, coalesce(external_unit, ''));

CREATE TABLE IF NOT EXISTS ble_profile_catalog (
  profile_code text PRIMARY KEY,
  display_name text NOT NULL,
  service_uuid text NOT NULL,
  required_characteristics jsonb NOT NULL DEFAULT '[]'::jsonb,
  optional_characteristics jsonb NOT NULL DEFAULT '[]'::jsonb,
  supported_metrics text[] NOT NULL DEFAULT ARRAY[]::text[],
  priority integer NOT NULL DEFAULT 100,
  parser_status text NOT NULL DEFAULT 'planned',
  bluetooth_spec_url text,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS connector_definitions (
  connector_code text PRIMARY KEY,
  display_name text NOT NULL,
  kind connector_kind NOT NULL,
  source_type source_type NOT NULL,
  auth_type text NOT NULL,
  supported_metrics text[] NOT NULL DEFAULT ARRAY[]::text[],
  supported_platforms text[] NOT NULL DEFAULT ARRAY[]::text[],
  consent_scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
  sync_modes text[] NOT NULL DEFAULT ARRAY[]::text[],
  expected_latency text,
  production_status text NOT NULL DEFAULT 'planned',
  docs_url text,
  active boolean NOT NULL DEFAULT true,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (auth_type IN ('local_permission', 'oauth2', 'api_key', 'none', 'fhir_oauth2')),
  CHECK (production_status IN ('planned', 'prototype', 'pilot', 'production', 'deprecated'))
);

CREATE TABLE IF NOT EXISTS patient_connector_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  connector_code text NOT NULL REFERENCES connector_definitions(connector_code) ON DELETE RESTRICT,
  status connector_account_status NOT NULL DEFAULT 'pending',
  external_account_hash text,
  token_vault_ref text,
  sync_cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
  permission_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_successful_sync_at timestamptz,
  last_error_code text,
  last_error_message text,
  revoked_at timestamptz,
  created_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS patient_connector_accounts_unique_idx
  ON patient_connector_accounts(patient_id, connector_code, coalesce(external_account_hash, 'local'));

CREATE INDEX IF NOT EXISTS patient_connector_accounts_patient_idx
  ON patient_connector_accounts(patient_id, status, connector_code);

CREATE TABLE IF NOT EXISTS connector_sync_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  connector_account_id uuid NOT NULL REFERENCES patient_connector_accounts(id) ON DELETE CASCADE,
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  status connector_sync_status NOT NULL DEFAULT 'queued',
  sync_window_start timestamptz,
  sync_window_end timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  raw_payloads_received integer NOT NULL DEFAULT 0,
  observations_created integer NOT NULL DEFAULT 0,
  observations_rejected integer NOT NULL DEFAULT 0,
  idempotency_key text,
  error_code text,
  error_message text,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS connector_sync_runs_idempotency_idx
  ON connector_sync_runs(connector_account_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS connector_sync_runs_patient_idx
  ON connector_sync_runs(patient_id, created_at DESC);

CREATE TABLE IF NOT EXISTS device_catalog_metric_support (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  catalog_device_id uuid NOT NULL REFERENCES device_catalog(id) ON DELETE CASCADE,
  metric_code text NOT NULL REFERENCES metric_catalog(metric_code) ON DELETE RESTRICT,
  connection_method text NOT NULL,
  expected_latency_seconds integer,
  validation_status text NOT NULL DEFAULT 'untested',
  limitations text[] NOT NULL DEFAULT ARRAY[]::text[],
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (catalog_device_id, metric_code, connection_method),
  CHECK (validation_status IN ('untested', 'community_tested', 'internally_tested', 'clinically_validated', 'deprecated'))
);

CREATE INDEX IF NOT EXISTS device_catalog_metric_support_metric_idx
  ON device_catalog_metric_support(metric_code, connection_method, validation_status);

CREATE TABLE IF NOT EXISTS device_support_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid REFERENCES patient_profiles(id) ON DELETE SET NULL,
  requested_by uuid REFERENCES user_accounts(id) ON DELETE SET NULL,
  brand text,
  model text,
  category text,
  requested_metrics text[] NOT NULL DEFAULT ARRAY[]::text[],
  platform text,
  country_code text,
  notes text,
  status text NOT NULL DEFAULT 'open',
  resolution_notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('open', 'triaged', 'planned', 'unsupported', 'completed', 'duplicate'))
);

CREATE INDEX IF NOT EXISTS device_support_requests_patient_idx
  ON device_support_requests(patient_id, created_at DESC);

CREATE TABLE IF NOT EXISTS observation_quality_assessments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL REFERENCES patient_profiles(id) ON DELETE CASCADE,
  observation_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  freshness freshness_status NOT NULL,
  quality_score numeric(5,4) NOT NULL,
  quality_flags text[] NOT NULL DEFAULT ARRAY[]::text[],
  source_observed_age_seconds integer,
  assessed_at timestamptz NOT NULL DEFAULT now(),
  quality_inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (observation_id, observed_at),
  FOREIGN KEY (observation_id, observed_at)
    REFERENCES observations(id, observed_at) ON DELETE CASCADE,
  CHECK (quality_score >= 0 AND quality_score <= 1)
);

CREATE INDEX IF NOT EXISTS observation_quality_assessments_patient_idx
  ON observation_quality_assessments(patient_id, assessed_at DESC);

CREATE TABLE IF NOT EXISTS observation_normalization_errors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id uuid REFERENCES patient_profiles(id) ON DELETE SET NULL,
  raw_payload_id uuid REFERENCES observation_raw_payloads(id) ON DELETE SET NULL,
  source_type source_type NOT NULL,
  external_metric_code text,
  error_code text NOT NULL,
  error_message text NOT NULL,
  payload_excerpt jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS observation_normalization_errors_patient_idx
  ON observation_normalization_errors(patient_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS simulator_scenarios (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_code text NOT NULL UNIQUE,
  display_name text NOT NULL,
  supported_metrics text[] NOT NULL DEFAULT ARRAY[]::text[],
  scenario_kind text NOT NULL DEFAULT 'observations',
  fixture_json jsonb NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS metric_catalog_set_updated_at ON metric_catalog;
CREATE TRIGGER metric_catalog_set_updated_at BEFORE UPDATE ON metric_catalog
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS metric_normalization_rules_set_updated_at ON metric_normalization_rules;
CREATE TRIGGER metric_normalization_rules_set_updated_at BEFORE UPDATE ON metric_normalization_rules
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS ble_profile_catalog_set_updated_at ON ble_profile_catalog;
CREATE TRIGGER ble_profile_catalog_set_updated_at BEFORE UPDATE ON ble_profile_catalog
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS connector_definitions_set_updated_at ON connector_definitions;
CREATE TRIGGER connector_definitions_set_updated_at BEFORE UPDATE ON connector_definitions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS patient_connector_accounts_set_updated_at ON patient_connector_accounts;
CREATE TRIGGER patient_connector_accounts_set_updated_at BEFORE UPDATE ON patient_connector_accounts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS connector_sync_runs_set_updated_at ON connector_sync_runs;
CREATE TRIGGER connector_sync_runs_set_updated_at BEFORE UPDATE ON connector_sync_runs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS device_catalog_metric_support_set_updated_at ON device_catalog_metric_support;
CREATE TRIGGER device_catalog_metric_support_set_updated_at BEFORE UPDATE ON device_catalog_metric_support
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS device_support_requests_set_updated_at ON device_support_requests;
CREATE TRIGGER device_support_requests_set_updated_at BEFORE UPDATE ON device_support_requests
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS simulator_scenarios_set_updated_at ON simulator_scenarios;
CREATE TRIGGER simulator_scenarios_set_updated_at BEFORE UPDATE ON simulator_scenarios
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE patient_connector_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_sync_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_support_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE observation_quality_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE observation_normalization_errors ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS patient_connector_accounts_scope ON patient_connector_accounts;
CREATE POLICY patient_connector_accounts_scope ON patient_connector_accounts
  USING (app_can_access_patient(patient_id, 'devices:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'devices:write'));

DROP POLICY IF EXISTS connector_sync_runs_scope ON connector_sync_runs;
CREATE POLICY connector_sync_runs_scope ON connector_sync_runs
  USING (app_can_access_patient(patient_id, 'devices:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'devices:write'));

DROP POLICY IF EXISTS device_support_requests_scope ON device_support_requests;
CREATE POLICY device_support_requests_scope ON device_support_requests
  USING (
    app_is_admin()
    OR requested_by = app_current_user_id()
    OR app_can_access_patient(patient_id, 'devices:read')
  )
  WITH CHECK (
    app_is_admin()
    OR requested_by = app_current_user_id()
    OR app_can_access_patient(patient_id, 'devices:write')
  );

DROP POLICY IF EXISTS observation_quality_assessments_scope ON observation_quality_assessments;
CREATE POLICY observation_quality_assessments_scope ON observation_quality_assessments
  USING (app_can_access_patient(patient_id, 'observations:read'))
  WITH CHECK (app_can_access_patient(patient_id, 'observations:write'));

DROP POLICY IF EXISTS observation_normalization_errors_scope ON observation_normalization_errors;
CREATE POLICY observation_normalization_errors_scope ON observation_normalization_errors
  USING (patient_id IS NULL OR app_can_access_patient(patient_id, 'observations:read'))
  WITH CHECK (patient_id IS NULL OR app_can_access_patient(patient_id, 'observations:write'));

INSERT INTO metric_catalog (
  metric_code,
  display_name,
  canonical_unit,
  accepted_units,
  value_kind,
  freshness_warning_after,
  freshness_stale_after,
  plausible_min,
  plausible_max,
  normal_range_strategy,
  fhir_codings
) VALUES
  ('heart_rate', 'Heart rate', 'bpm', ARRAY['bpm', 'count/min'], 'numeric', interval '5 minutes', interval '15 minutes', 20, 240, 'patient_specific', '[{"system":"http://loinc.org","code":"8867-4","display":"Heart rate"}]'::jsonb),
  ('blood_pressure_systolic', 'Blood pressure systolic', 'mmHg', ARRAY['mmHg', 'kPa'], 'numeric', interval '30 minutes', interval '2 hours', 50, 260, 'patient_specific', '[{"system":"http://loinc.org","code":"8480-6","display":"Systolic blood pressure"}]'::jsonb),
  ('blood_pressure_diastolic', 'Blood pressure diastolic', 'mmHg', ARRAY['mmHg', 'kPa'], 'numeric', interval '30 minutes', interval '2 hours', 30, 180, 'patient_specific', '[{"system":"http://loinc.org","code":"8462-4","display":"Diastolic blood pressure"}]'::jsonb),
  ('blood_glucose', 'Blood glucose', 'mg/dL', ARRAY['mg/dL', 'mmol/L'], 'numeric', interval '30 minutes', interval '2 hours', 20, 700, 'patient_specific', '[{"system":"http://loinc.org","code":"2339-0","display":"Glucose [Mass/volume] in Blood"}]'::jsonb),
  ('continuous_glucose', 'Continuous glucose', 'mg/dL', ARRAY['mg/dL', 'mmol/L'], 'numeric', interval '15 minutes', interval '45 minutes', 20, 700, 'patient_specific', '[{"system":"http://loinc.org","code":"14745-4","display":"Glucose [Moles/volume] in Body fluid"}]'::jsonb),
  ('spo2', 'Oxygen saturation', '%', ARRAY['%', 'fraction'], 'numeric', interval '5 minutes', interval '15 minutes', 50, 100, 'patient_specific', '[{"system":"http://loinc.org","code":"59408-5","display":"Oxygen saturation in Arterial blood by Pulse oximetry"}]'::jsonb),
  ('body_temperature', 'Body temperature', 'degC', ARRAY['degC', 'degF'], 'numeric', interval '2 hours', interval '8 hours', 30, 45, 'patient_specific', '[{"system":"http://loinc.org","code":"8310-5","display":"Body temperature"}]'::jsonb),
  ('weight', 'Weight', 'kg', ARRAY['kg', 'lb', 'g'], 'numeric', interval '7 days', interval '30 days', 1, 400, 'patient_specific', '[{"system":"http://loinc.org","code":"29463-7","display":"Body weight"}]'::jsonb),
  ('respiratory_rate', 'Respiratory rate', 'breaths/min', ARRAY['breaths/min'], 'numeric', interval '15 minutes', interval '1 hour', 4, 80, 'patient_specific', '[{"system":"http://loinc.org","code":"9279-1","display":"Respiratory rate"}]'::jsonb),
  ('step_count', 'Steps', 'count', ARRAY['count'], 'numeric', interval '1 day', interval '2 days', 0, 200000, 'baseline', '[{"system":"http://loinc.org","code":"41950-7","display":"Number of steps in 24 hour Measured"}]'::jsonb),
  ('sleep_duration', 'Sleep duration', 'min', ARRAY['min', 'hr', 's'], 'numeric', interval '1 day', interval '2 days', 0, 1440, 'baseline', '[]'::jsonb),
  ('fall_detected', 'Fall detected', 'boolean', ARRAY['boolean', 'count'], 'boolean', interval '0 seconds', interval '15 minutes', NULL, NULL, 'event_policy', '[]'::jsonb)
ON CONFLICT (metric_code) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  canonical_unit = EXCLUDED.canonical_unit,
  accepted_units = EXCLUDED.accepted_units,
  freshness_warning_after = EXCLUDED.freshness_warning_after,
  freshness_stale_after = EXCLUDED.freshness_stale_after,
  plausible_min = EXCLUDED.plausible_min,
  plausible_max = EXCLUDED.plausible_max,
  normal_range_strategy = EXCLUDED.normal_range_strategy,
  fhir_codings = EXCLUDED.fhir_codings;

INSERT INTO connector_definitions (
  connector_code,
  display_name,
  kind,
  source_type,
  auth_type,
  supported_metrics,
  supported_platforms,
  consent_scopes,
  sync_modes,
  expected_latency,
  production_status,
  docs_url
) VALUES
  ('healthkit', 'Apple HealthKit', 'os_health_store', 'healthkit', 'local_permission',
   ARRAY['heart_rate','blood_pressure_systolic','blood_pressure_diastolic','blood_glucose','spo2','body_temperature','weight','respiratory_rate','step_count','sleep_duration','fall_detected'],
   ARRAY['ios'], ARRAY['health_data:read'], ARRAY['incremental','background_where_allowed'], 'Phone-mediated; may be delayed by OS background policy', 'planned',
   'https://developer.apple.com/documentation/healthkit'),
  ('health_connect', 'Android Health Connect', 'os_health_store', 'health_connect', 'local_permission',
   ARRAY['heart_rate','blood_pressure_systolic','blood_pressure_diastolic','blood_glucose','spo2','body_temperature','weight','respiratory_rate','step_count','sleep_duration'],
   ARRAY['android'], ARRAY['health_data:read'], ARRAY['incremental'], 'Phone-mediated; depends on Health Connect source app sync', 'planned',
   'https://developer.android.com/health-and-fitness/health-connect'),
  ('ble_medical_profiles', 'Standard BLE Medical Profiles', 'standard_ble', 'ble', 'local_permission',
   ARRAY['heart_rate','blood_pressure_systolic','blood_pressure_diastolic','blood_glucose','continuous_glucose','spo2','body_temperature','weight'],
   ARRAY['ios','android'], ARRAY['bluetooth:scan','bluetooth:connect','health_data:read'], ARRAY['streaming','batch'], 'Near real-time while phone is connected; may be stale when disconnected', 'planned',
   'https://www.bluetooth.com/specifications/specs/'),
  ('vendor_api_framework', 'Vendor API Framework', 'vendor_api', 'vendor_api', 'oauth2',
   ARRAY['heart_rate','blood_pressure_systolic','blood_pressure_diastolic','blood_glucose','continuous_glucose','spo2','body_temperature','weight','respiratory_rate','step_count','sleep_duration','fall_detected'],
   ARRAY['ios','android','web'], ARRAY['health_data:read','offline_access'], ARRAY['incremental','webhook'], 'Vendor/cloud dependent; display source latency', 'planned',
   NULL),
  ('fhir_import', 'FHIR Observation Import', 'clinical_fhir', 'fhir', 'fhir_oauth2',
   ARRAY['heart_rate','blood_pressure_systolic','blood_pressure_diastolic','blood_glucose','spo2','body_temperature','weight','respiratory_rate'],
   ARRAY['ios','android','web'], ARRAY['clinical_records:read'], ARRAY['batch','incremental'], 'Clinical portal dependent', 'planned',
   'https://hl7.org/fhir/observation.html'),
  ('manual_entry', 'Manual Reading Entry', 'manual', 'manual', 'none',
   ARRAY['heart_rate','blood_pressure_systolic','blood_pressure_diastolic','blood_glucose','spo2','body_temperature','weight','respiratory_rate','fall_detected'],
   ARRAY['ios','android','web'], ARRAY['manual_entry:write'], ARRAY['manual'], 'Immediate after user entry', 'planned',
   NULL),
  ('ocr_reading', 'OCR Reading Extraction', 'ocr', 'ocr', 'none',
   ARRAY['blood_pressure_systolic','blood_pressure_diastolic','blood_glucose','spo2','body_temperature','weight'],
   ARRAY['ios','android','web'], ARRAY['documents:write'], ARRAY['batch'], 'Depends on OCR processing and review', 'planned',
   NULL),
  ('device_simulator', 'Device Simulator', 'simulator', 'simulator', 'none',
   ARRAY['heart_rate','blood_pressure_systolic','blood_pressure_diastolic','blood_glucose','continuous_glucose','spo2','body_temperature','weight','respiratory_rate','step_count','sleep_duration','fall_detected'],
   ARRAY['web'], ARRAY['test:write'], ARRAY['scenario'], 'Deterministic test/demo only; disabled in production', 'prototype',
   NULL)
ON CONFLICT (connector_code) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  kind = EXCLUDED.kind,
  source_type = EXCLUDED.source_type,
  auth_type = EXCLUDED.auth_type,
  supported_metrics = EXCLUDED.supported_metrics,
  supported_platforms = EXCLUDED.supported_platforms,
  consent_scopes = EXCLUDED.consent_scopes,
  sync_modes = EXCLUDED.sync_modes,
  expected_latency = EXCLUDED.expected_latency,
  production_status = EXCLUDED.production_status,
  docs_url = EXCLUDED.docs_url;

INSERT INTO ble_profile_catalog (
  profile_code,
  display_name,
  service_uuid,
  required_characteristics,
  optional_characteristics,
  supported_metrics,
  priority,
  parser_status,
  bluetooth_spec_url,
  notes
) VALUES
  ('heart_rate', 'Heart Rate Service', '0000180d-0000-1000-8000-00805f9b34fb',
   '[{"name":"Heart Rate Measurement","uuid":"00002a37-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   '[{"name":"Body Sensor Location","uuid":"00002a38-0000-1000-8000-00805f9b34fb"},{"name":"Heart Rate Control Point","uuid":"00002a39-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   ARRAY['heart_rate'], 0, 'planned', 'https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/', 'First BLE parser target.'),
  ('blood_pressure', 'Blood Pressure Service', '00001810-0000-1000-8000-00805f9b34fb',
   '[{"name":"Blood Pressure Measurement","uuid":"00002a35-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   '[{"name":"Intermediate Cuff Pressure","uuid":"00002a36-0000-1000-8000-00805f9b34fb"},{"name":"Blood Pressure Feature","uuid":"00002a49-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   ARRAY['blood_pressure_systolic','blood_pressure_diastolic','heart_rate'], 0, 'planned', 'https://www.bluetooth.com/specifications/specs/blood-pressure-service-1-1-1/', 'Create grouped systolic/diastolic observations.'),
  ('glucose', 'Glucose Service', '00001808-0000-1000-8000-00805f9b34fb',
   '[{"name":"Glucose Measurement","uuid":"00002a18-0000-1000-8000-00805f9b34fb"},{"name":"Record Access Control Point","uuid":"00002a52-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   '[{"name":"Glucose Measurement Context","uuid":"00002a34-0000-1000-8000-00805f9b34fb"},{"name":"Glucose Feature","uuid":"00002a51-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   ARRAY['blood_glucose'], 0, 'planned', 'https://www.bluetooth.com/specifications/specs/glucose-service-1-0-1/', 'MVP alternative to pulse oximeter based on pilot device ownership.'),
  ('pulse_oximeter', 'Pulse Oximeter Service', '00001822-0000-1000-8000-00805f9b34fb',
   '[{"name":"PLX Spot-check Measurement","uuid":"00002a5e-0000-1000-8000-00805f9b34fb"},{"name":"PLX Features","uuid":"00002a60-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   '[{"name":"PLX Continuous Measurement","uuid":"00002a5f-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   ARRAY['spo2','heart_rate'], 0, 'planned', 'https://www.bluetooth.com/specifications/specs/pulse-oximeter-service-1-0-1/', 'MVP alternative to glucose based on pilot device ownership.'),
  ('health_thermometer', 'Health Thermometer Service', '00001809-0000-1000-8000-00805f9b34fb',
   '[{"name":"Temperature Measurement","uuid":"00002a1c-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   '[{"name":"Temperature Type","uuid":"00002a1d-0000-1000-8000-00805f9b34fb"},{"name":"Intermediate Temperature","uuid":"00002a1e-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   ARRAY['body_temperature'], 1, 'planned', 'https://www.bluetooth.com/specifications/specs/health-thermometer-service-1-0/', 'Second-wave parser.'),
  ('weight_scale', 'Weight Scale Service', '0000181d-0000-1000-8000-00805f9b34fb',
   '[{"name":"Weight Measurement","uuid":"00002a9d-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   '[{"name":"Weight Scale Feature","uuid":"00002a9e-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   ARRAY['weight'], 1, 'planned', 'https://www.bluetooth.com/specifications/specs/weight-scale-service-1-0/', 'Second-wave parser.'),
  ('continuous_glucose', 'Continuous Glucose Monitoring Service', '0000181f-0000-1000-8000-00805f9b34fb',
   '[{"name":"CGM Measurement","uuid":"00002aa7-0000-1000-8000-00805f9b34fb"},{"name":"CGM Feature","uuid":"00002aa8-0000-1000-8000-00805f9b34fb"},{"name":"Record Access Control Point","uuid":"00002a52-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   '[{"name":"CGM Status","uuid":"00002aa9-0000-1000-8000-00805f9b34fb"},{"name":"CGM Session Start Time","uuid":"00002aaa-0000-1000-8000-00805f9b34fb"},{"name":"CGM Session Run Time","uuid":"00002aab-0000-1000-8000-00805f9b34fb"}]'::jsonb,
   ARRAY['continuous_glucose'], 2, 'planned', 'https://www.bluetooth.com/specifications/specs/continuous-glucose-monitoring-service-1-0-3/', 'Requires device/vendor/regulatory review before pilot.')
ON CONFLICT (profile_code) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  service_uuid = EXCLUDED.service_uuid,
  required_characteristics = EXCLUDED.required_characteristics,
  optional_characteristics = EXCLUDED.optional_characteristics,
  supported_metrics = EXCLUDED.supported_metrics,
  priority = EXCLUDED.priority,
  parser_status = EXCLUDED.parser_status,
  bluetooth_spec_url = EXCLUDED.bluetooth_spec_url,
  notes = EXCLUDED.notes;

INSERT INTO metric_normalization_rules (
  source_type,
  external_metric_code,
  metric_code,
  external_unit,
  canonical_unit,
  conversion_expression,
  value_path,
  timestamp_path,
  default_reliability_tier,
  notes
) VALUES
  ('healthkit', 'heartRate', 'heart_rate', 'count/min', 'bpm', NULL, '$.quantity', '$.startDate', 'os_aggregator', 'Preserve HKSourceRevision and motion context metadata.'),
  ('healthkit', 'bloodPressureSystolic', 'blood_pressure_systolic', 'mmHg', 'mmHg', NULL, '$.quantity', '$.startDate', 'os_aggregator', 'Link with diastolic using HealthKit correlation when available.'),
  ('healthkit', 'bloodPressureDiastolic', 'blood_pressure_diastolic', 'mmHg', 'mmHg', NULL, '$.quantity', '$.startDate', 'os_aggregator', 'Link with systolic using HealthKit correlation when available.'),
  ('healthkit', 'bloodGlucose', 'blood_glucose', 'mg/dL', 'mg/dL', NULL, '$.quantity', '$.startDate', 'os_aggregator', NULL),
  ('healthkit', 'oxygenSaturation', 'spo2', 'fraction', '%', 'value * 100', '$.quantity', '$.startDate', 'os_aggregator', NULL),
  ('healthkit', 'bodyTemperature', 'body_temperature', 'degF', 'degC', '(value - 32) * 5 / 9', '$.quantity', '$.startDate', 'os_aggregator', NULL),
  ('healthkit', 'bodyMass', 'weight', 'kg', 'kg', NULL, '$.quantity', '$.startDate', 'os_aggregator', NULL),
  ('healthkit', 'respiratoryRate', 'respiratory_rate', 'count/min', 'breaths/min', NULL, '$.quantity', '$.startDate', 'os_aggregator', NULL),
  ('healthkit', 'stepCount', 'step_count', 'count', 'count', NULL, '$.quantity', '$.startDate', 'os_aggregator', NULL),
  ('healthkit', 'sleepAnalysis', 'sleep_duration', 'min', 'min', NULL, '$.durationMinutes', '$.startDate', 'os_aggregator', 'Compute from HealthKit sleep category sample intervals.'),
  ('healthkit', 'numberOfTimesFallen', 'fall_detected', 'count', 'boolean', 'value > 0', '$.quantity', '$.startDate', 'os_aggregator', 'Convert count deltas into event observations.'),
  ('health_connect', 'HeartRateRecord', 'heart_rate', 'bpm', 'bpm', NULL, '$.samples[*].beatsPerMinute', '$.samples[*].time', 'os_aggregator', NULL),
  ('health_connect', 'BloodPressureRecord.systolic', 'blood_pressure_systolic', 'mmHg', 'mmHg', NULL, '$.systolic', '$.time', 'os_aggregator', NULL),
  ('health_connect', 'BloodPressureRecord.diastolic', 'blood_pressure_diastolic', 'mmHg', 'mmHg', NULL, '$.diastolic', '$.time', 'os_aggregator', NULL),
  ('health_connect', 'BloodGlucoseRecord', 'blood_glucose', 'mg/dL', 'mg/dL', NULL, '$.level', '$.time', 'os_aggregator', NULL),
  ('health_connect', 'OxygenSaturationRecord', 'spo2', '%', '%', NULL, '$.percentage', '$.time', 'os_aggregator', NULL),
  ('health_connect', 'BodyTemperatureRecord', 'body_temperature', 'degC', 'degC', NULL, '$.temperature', '$.time', 'os_aggregator', NULL),
  ('health_connect', 'WeightRecord', 'weight', 'kg', 'kg', NULL, '$.weight', '$.time', 'os_aggregator', NULL),
  ('health_connect', 'RespiratoryRateRecord', 'respiratory_rate', 'breaths/min', 'breaths/min', NULL, '$.rate', '$.time', 'os_aggregator', NULL),
  ('health_connect', 'StepsRecord', 'step_count', 'count', 'count', NULL, '$.count', '$.startTime', 'os_aggregator', NULL),
  ('health_connect', 'SleepSessionRecord', 'sleep_duration', 'min', 'min', NULL, '$.durationMinutes', '$.startTime', 'os_aggregator', 'Compute duration from sleep session interval; preserve stage details in fhir_json.'),
  ('ble', 'heart_rate.heart_rate_measurement', 'heart_rate', 'bpm', 'bpm', NULL, '$.heart_rate_bpm', '$.device_time', 'standard_ble', 'Bluetooth Heart Rate Measurement characteristic 0x2A37.'),
  ('ble', 'blood_pressure.systolic', 'blood_pressure_systolic', 'mmHg', 'mmHg', NULL, '$.systolic', '$.device_time', 'standard_ble', 'Bluetooth Blood Pressure Measurement characteristic 0x2A35.'),
  ('ble', 'blood_pressure.diastolic', 'blood_pressure_diastolic', 'mmHg', 'mmHg', NULL, '$.diastolic', '$.device_time', 'standard_ble', 'Bluetooth Blood Pressure Measurement characteristic 0x2A35.'),
  ('ble', 'glucose.glucose_measurement', 'blood_glucose', 'mg/dL', 'mg/dL', NULL, '$.glucose', '$.device_time', 'standard_ble', 'Bluetooth Glucose Measurement characteristic 0x2A18.'),
  ('ble', 'pulse_oximeter.spo2', 'spo2', '%', '%', NULL, '$.spo2_percent', '$.device_time', 'standard_ble', 'Bluetooth PLX Spot-check or Continuous Measurement.'),
  ('ble', 'health_thermometer.temperature', 'body_temperature', 'degC', 'degC', NULL, '$.temperature', '$.device_time', 'standard_ble', 'Bluetooth Temperature Measurement characteristic 0x2A1C.'),
  ('ble', 'weight_scale.weight', 'weight', 'kg', 'kg', NULL, '$.weight', '$.device_time', 'standard_ble', 'Bluetooth Weight Measurement characteristic 0x2A9D.'),
  ('manual', 'manual_value', 'heart_rate', 'bpm', 'bpm', NULL, '$.value', '$.observed_at', 'manual_or_ocr', 'Metric-specific manual entry rule; keep review metadata.'),
  ('ocr', 'ocr_value', 'spo2', '%', '%', NULL, '$.extracted_value', '$.observed_at', 'manual_or_ocr', 'Metric-specific OCR rule; require review for high-risk use.')
ON CONFLICT (source_type, external_metric_code, metric_code, (coalesce(external_unit, ''))) DO UPDATE SET
  canonical_unit = EXCLUDED.canonical_unit,
  conversion_expression = EXCLUDED.conversion_expression,
  value_path = EXCLUDED.value_path,
  timestamp_path = EXCLUDED.timestamp_path,
  default_reliability_tier = EXCLUDED.default_reliability_tier,
  notes = EXCLUDED.notes,
  active = true;

COMMIT;
