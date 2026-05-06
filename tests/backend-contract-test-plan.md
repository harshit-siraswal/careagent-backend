# Backend Unit and Integration Test Plan

This test plan is written against `backend/openapi/careagent-backend-v1.yaml` and `backend/migrations/001_initial_backend_platform.sql`. It should become executable pytest suites when the FastAPI service is scaffolded.

## Test Harness Assumptions

- PostgreSQL runs migrations from `backend/migrations`.
- API tests use FastAPI `TestClient` or HTTPX against an app with dependency overrides.
- Auth provider verification is mocked but still exercises `auth_identities` resolution.
- Object storage, malware scanner, OCR, notification, Telegram, WhatsApp, and voice providers use fakes.
- Queue publishing is tested through `outbox_events` rows and fake worker drains.
- Every API response includes a `request_id`.

## Unit Tests

### Auth and RBAC

| Test | Assertions |
| --- | --- |
| `test_session_creates_or_resolves_auth_identity` | Valid provider token maps to one `user_accounts` row and one `auth_identities` row. |
| `test_disabled_account_cannot_create_session` | Disabled account returns 403 and audits `auth.session_denied`. |
| `test_patient_can_access_own_profile` | Patient owner passes `patient:read` without `patient_access_grants`. |
| `test_caretaker_requires_active_patient_grant` | Caretaker without active grant gets 403 and no PHI payload. |
| `test_expired_grant_is_denied` | Expired grant is ignored by authorization. |
| `test_revoked_grant_is_denied` | Revoked grant is ignored by authorization. |
| `test_write_requires_write_permission` | `patient:read` does not allow `PATCH /patients/{id}`. |
| `test_admin_phi_access_requires_break_glass_reason` | Admin PHI read without reason/MFA is denied. |
| `test_denied_phi_attempt_creates_audit_event` | 403 on a patient-scoped route writes `audit_logs.outcome = denied`. |

### Consent Policy

| Test | Assertions |
| --- | --- |
| `test_consent_grant_appends_ledger_event` | `consent_grants` and `consent_ledger` are inserted in one transaction. |
| `test_consent_revoke_blocks_future_channel_actions` | Revoked WhatsApp/call/location consent prevents outbound action. |
| `test_emergency_escalation_requires_emergency_consent` | Critical risk event cannot start emergency-enabled policy without active consent. |
| `test_location_omitted_without_location_consent` | Escalation message variables omit location even if policy step requests it. |
| `test_consent_expiry_worker_marks_expired` | Expired consent changes status and appends `consent.expired` audit/event. |

### Observations

| Test | Assertions |
| --- | --- |
| `test_observation_batch_validates_patient_scope` | Patient ID in path is authoritative; body cannot override it. |
| `test_observation_requires_value_numeric_or_text` | Empty reading is rejected with 422. |
| `test_observation_unit_normalization` | Known units normalize before insert and preserve raw payload. |
| `test_observation_batch_writes_one_outbox_event` | Batch insert creates one `observation.created` event. |
| `test_latest_vitals_returns_most_recent_per_metric` | Latest query respects observed time and metric grouping. |
| `test_partition_indexes_exist_for_observations` | Migration creates partitioned/default observation indexes; partition creation helper creates same indexes. |

### Documents

| Test | Assertions |
| --- | --- |
| `test_document_upload_session_requires_idempotency_key` | Missing `Idempotency-Key` returns 400. |
| `test_document_upload_session_returns_signed_storage_url` | API creates metadata with `malware_scan_status = pending` and signed upload target. |
| `test_duplicate_document_hash_is_idempotent_per_patient` | Same patient/sha256 returns existing document/session according to idempotency policy. |
| `test_document_download_blocked_until_clean_scan` | Pending/infected/failed scan states deny raw object access. |
| `test_infected_document_is_quarantined_and_not_ocrd` | Malware worker marks quarantine and no OCR event is published. |
| `test_extraction_review_updates_fact_status` | Approve/correct/reject changes fact state and writes audit event. |
| `test_patient_question_uses_only_approved_facts` | RAG/answer layer excludes pending/rejected facts. |

### Medicines

| Test | Assertions |
| --- | --- |
| `test_schedule_from_extraction_requires_review` | Extracted schedule starts `review_status = pending`; reminders do not arm until approved. |
| `test_dose_event_records_actor_and_channel` | Dose event includes `recorded_by`, `source_channel`, audit event. |
| `test_duplicate_dose_event_is_idempotent` | Same schedule/scheduled_at/status/idempotency key does not duplicate records. |
| `test_missed_dose_worker_emits_risk_event_when_policy_matches` | Missed dose creates configured alert/risk path only when consent allows caretaker notification. |

### Risk and Escalation

| Test | Assertions |
| --- | --- |
| `test_risk_event_creation_requires_idempotency_key` | Missing key returns 400 for API-created risk event. |
| `test_risk_event_unique_by_patient_and_key` | Replay returns original risk event and does not duplicate alerts. |
| `test_high_risk_creates_alert` | High/critical event creates patient alert and outbox notification event. |
| `test_escalation_start_is_idempotent` | Repeated request returns same `escalation_run_id`; no duplicate action rows. |
| `test_escalation_unique_by_risk_event_and_policy` | Different header key for same risk/policy returns existing run with audit metadata. |
| `test_escalation_step_respects_retry_limit` | Worker attempts exactly configured count and then fails/fallbacks. |
| `test_voice_call_requires_ai_disclosure_script` | Voice action cannot dispatch without approved script/template ID. |
| `test_simulation_mode_never_calls_real_emergency_provider` | Emergency drill uses fake provider and marks all actions simulation-safe. |

### Agent Tool Policy

| Test | Assertions |
| --- | --- |
| `test_tool_request_requires_patient_id_actor_request_reason` | Missing contract fields return 422. |
| `test_get_recent_vitals_requires_observation_read` | Tool denied without `observations:read`. |
| `test_send_channel_message_requires_consent_and_template` | Outbound message denied without channel consent or approved template. |
| `test_place_voice_call_requires_call_consent` | Voice tool denied without call consent. |
| `test_start_escalation_tool_delegates_to_idempotent_escalation` | Tool returns existing escalation run on replay. |
| `test_tool_call_writes_input_output_policy_and_audit` | `agent_tool_calls` row links to `audit_logs`. |

### Audit Logging

| Test | Assertions |
| --- | --- |
| `test_phi_read_audited_before_response` | PHI endpoint writes audit row in success path. |
| `test_audit_logs_are_append_only` | Update/delete attempts on `audit_logs` fail. |
| `test_audit_metadata_is_redacted` | Signed URLs, tokens, raw document text, and full prompts are not stored. |
| `test_audit_hash_chain_validates` | Hash chain utility detects tampering. |

## Integration Tests

### End-to-End Patient Setup

1. Create patient session.
2. Create patient profile.
3. Add caretaker contact and linked user grant.
4. Grant health data, caretaker access, messaging, calls, location, and emergency automation consents.
5. Assert all writes have audit rows and consent ledger entries.

Expected result: caretaker can read only the granted patient and cannot access a second patient.

### Device to Risk to Alert

1. Register a simulated pulse oximeter.
2. Ingest a batch with SpO2 below threshold.
3. Drain observation/risk queues.
4. Assert observation row, risk event, alert, outbox events, and audit events exist.
5. Caretaker acknowledges alert.

Expected result: acknowledgement updates risk/alert state and audits the actor.

### Document Upload and Extraction

1. Create document upload session.
2. Simulate object-storage completion.
3. Drain malware scan with clean result.
4. Drain OCR and extraction workers.
5. Approve one extracted medicine fact and correct one lab fact.
6. Ask a document question.

Expected result: pending scan blocks OCR; clean scan enables extraction; answer contains citations and audit ID.

### Medicine Reminder and Missed Dose

1. Create medicine from approved extraction.
2. Approve schedule.
3. Worker emits due dose event.
4. Do not record taken status before grace period.
5. Missed dose worker creates missed event and, if policy/consent allow, caretaker alert.

Expected result: local reminder schedule is generated, missed dose is idempotent, caretaker notification respects consent.

### Critical Escalation

1. Configure critical escalation policy with patient prompt, caretaker message, caretaker call, doctor fallback, and simulation-mode emergency step.
2. Create critical risk event with idempotency key.
3. Start escalation twice with same key.
4. Drain escalation and dispatch workers.
5. Simulate voice provider answer and caretaker acknowledgement.

Expected result: one escalation run, deterministic action sequence, no duplicate calls, AI disclosure template used, location included only when consented, timeline/audit complete.

### Webhook Security

1. Send WhatsApp/Telegram/voice webhook with invalid signature.
2. Send valid webhook replay with same provider message ID.
3. Send valid webhook that includes media upload.

Expected result: invalid signature denied and audited, replay is idempotent, media upload creates document metadata and scan event only after channel identity is verified.

### Unauthorized Cross-Patient Access

1. Create two patients and one caretaker granted to patient A only.
2. Attempt all patient-scoped GET/POST routes for patient B.
3. Attempt resource-ID routes where the ID belongs to patient B but the path/body claims patient A.

Expected result: all attempts return 403 or 404 according to leak-prevention policy, no PHI leaks, denied audit rows are created.

## Load and Reliability Tests

| Test | Target |
| --- | --- |
| `load_observation_ingest_100k_per_hour` | Inserts remain within SLO using partitions and batch writes. |
| `load_latest_vitals_multi_patient` | Latest vitals query uses index/cache and stays below API latency target. |
| `load_simultaneous_critical_alerts` | First outbound attempt starts within 60 seconds under expected pilot load. |
| `chaos_notification_provider_down` | Escalation falls back channels without duplicate calls/messages. |
| `chaos_worker_replay_outbox_events` | Replayed events are idempotent across risk, alert, escalation, and document facts. |

## Security Tests

| Test | Target |
| --- | --- |
| `security_prompt_injection_uploaded_document` | Extraction/RAG does not follow instructions embedded in documents. |
| `security_prompt_injection_channel_message` | Agent does not leak records or bypass tool policy from channel instructions. |
| `security_signed_url_not_logged` | Signed object-storage URLs are never persisted in logs/audit metadata. |
| `security_webhook_replay_window` | Old webhook signatures and duplicate provider IDs are rejected/replayed safely. |
| `security_rbac_matrix_all_routes` | Parametrized route test enforces the authorization matrix. |

## Acceptance Gate

Backend MVP is not ready until:

- All RBAC matrix tests pass.
- All PHI endpoints have audit assertions.
- Escalation idempotency tests pass.
- Document malware-scan blocking tests pass.
- Observation ingestion load test meets pilot target.
- Webhook signature and replay tests pass.
- Critical escalation simulation produces a complete incident timeline.
