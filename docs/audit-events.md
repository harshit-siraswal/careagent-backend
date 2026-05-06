# Audit Event Catalogue

Audit logs are append-only. Every PHI access, permission change, consent change, agent tool call, external message/call, webhook side effect, escalation action, and admin support action writes one `audit_logs` row.

## Required Fields

| Field | Requirement |
| --- | --- |
| `actor_type` | `user`, `system`, `agent`, `provider_webhook`, or `background_worker`. |
| `actor_id` | Provider/user/worker identity as string. |
| `actor_user_id` | Set when the actor maps to a `user_accounts.id`. |
| `patient_id` | Required for patient-scoped or PHI events when known. |
| `action` | Stable event name from this catalogue. |
| `resource_type` | Domain object, such as `medical_document` or `risk_event`. |
| `resource_id` | Object ID when known. |
| `outcome` | `success`, `denied`, or `error`. Denied PHI attempts are audited. |
| `phi_access` | `true` for any PHI read/write or generated answer derived from PHI. |
| `reason` | Required for admin break-glass, agent tool calls, escalation starts, and denied PHI attempts. |
| `request_id` | API or worker correlation ID. |
| `metadata_json` | Redacted context; never include raw PHI unless unavoidable for incident review. |
| `previous_hash`, `entry_hash` | Optional hash-chain fields for tamper evidence. |

## PHI Access Rule

PHI includes patient profile details, contacts, consent state, observations/vitals, device health linked to a patient, medicines, dose history, documents, extracted facts, risk events, alerts, conversations, agent answers, escalation timelines, calls, messages, and location.

The API should create the audit row before returning PHI. If a response streams or paginates PHI, the audit event records the query shape and result count, not the raw result content.

## Event Catalogue

### Auth and Account

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `auth.session_created` | `auth_session` | No | Provider token exchanged successfully. |
| `auth.session_denied` | `auth_session` | No | Provider token rejected or account disabled. |
| `auth.me_viewed` | `user_account` | No | Current user profile and grants returned. |
| `auth.mfa_required` | `user_account` | No | Actor blocked until MFA. |

### Patient and Care Team

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `patient.profile_created` | `patient_profile` | Yes | Patient profile created. |
| `patient.profile_viewed` | `patient_profile` | Yes | Patient profile read. |
| `patient.profile_updated` | `patient_profile` | Yes | Patient profile updated. |
| `patient.roster_viewed` | `patient_profile` | Yes | Multi-patient list viewed. |
| `care_team.viewed` | `care_team_member` | Yes | Care team or contact list viewed. |
| `care_team.member_added` | `care_team_member` | Yes | Contact or account added to care team. |
| `care_team.member_updated` | `care_team_member` | Yes | Care team role, priority, contact, or permissions changed. |
| `patient.access_granted` | `patient_access_grant` | Yes | Patient-scoped grant created. |
| `patient.access_revoked` | `patient_access_grant` | Yes | Patient-scoped grant revoked. |

### Consent Ledger

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `consent.viewed` | `consent_grant` | Yes | Consent state or ledger viewed. |
| `consent.granted` | `consent_grant` | Yes | Consent grant created and ledger row appended. |
| `consent.updated` | `consent_grant` | Yes | Consent scope, expiry, or channel changed. |
| `consent.revoked` | `consent_grant` | Yes | Consent revoked and ledger row appended. |
| `consent.expired` | `consent_grant` | Yes | Expiry worker marks consent expired. |

### Devices and Observations

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `devices.viewed` | `device` | Yes | Device list or connection state viewed. |
| `device.registered` | `device` | Yes | Device registered to patient. |
| `device.connection_updated` | `device_connection` | Yes | Connection, freshness, battery, or error state changed. |
| `observations.queried` | `observation` | Yes | Observation history queried. |
| `observation.created` | `observation` | Yes | Observation batch accepted or inserted. |
| `vitals.latest_viewed` | `observation` | Yes | Latest vitals endpoint viewed. |
| `observation.raw_payload_viewed` | `observation_raw_payload` | Yes | Raw payload accessed for debugging or incident review. |

### Documents

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `documents.list_viewed` | `medical_document` | Yes | Document list viewed. |
| `document.upload_session_created` | `medical_document` | Yes | Signed object-storage upload URL created. |
| `document.upload_completed` | `medical_document` | Yes | Storage confirms object upload. |
| `document.malware_scan_completed` | `medical_document` | Yes | Malware scan result persisted. |
| `document.viewed` | `medical_document` | Yes | Document metadata/facts viewed. |
| `document.downloaded` | `medical_document` | Yes | Clean raw object downloaded through controlled URL. |
| `document.status_viewed` | `medical_document` | Yes | Processing status viewed. |
| `document.ocr_completed` | `document_processing_run` | Yes | OCR worker completed. |
| `document.extraction_completed` | `document_processing_run` | Yes | Extraction worker completed. |
| `document.extraction_reviewed` | `extracted_medical_fact` | Yes | Extracted fact approved/corrected/rejected. |
| `document.question_answered` | `agent_answer` | Yes | Source-cited answer generated from patient records. |

### Medicines

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `medicines.viewed` | `medicine` | Yes | Medicine list viewed. |
| `medicine.created` | `medicine` | Yes | Medicine created. |
| `medicine.updated` | `medicine` | Yes | Medicine changed or deactivated. |
| `medicine_schedule.viewed` | `medicine_schedule` | Yes | Schedule viewed. |
| `medicine_schedule.upserted` | `medicine_schedule` | Yes | Schedule created, changed, or approved. |
| `medicine_dose.recorded` | `medicine_dose_event` | Yes | Dose taken/skipped/snoozed/missed recorded. |
| `medicine_dose.missed_detected` | `medicine_dose_event` | Yes | Worker marks missed dose. |

### Risk, Alerts, and Escalation

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `risk_event.created` | `risk_event` | Yes | Risk event created. |
| `risk_event.viewed` | `risk_event` | Yes | Risk event viewed. |
| `risk_event.acknowledged` | `risk_event` | Yes | Risk event acknowledged. |
| `risk_event.resolved` | `risk_event` | Yes | Risk event resolved or classified. |
| `alerts.viewed` | `alert` | Yes | Alert list viewed. |
| `alert.created` | `alert` | Yes | Alert created from risk event. |
| `alert.acknowledged` | `alert` | Yes | Alert acknowledged. |
| `escalation_policies.viewed` | `escalation_policy` | Yes | Escalation policy viewed. |
| `escalation_policy.created` | `escalation_policy` | Yes | Policy created. |
| `escalation_policy.updated` | `escalation_policy` | Yes | Policy or step changed. |
| `escalation.started` | `escalation_run` | Yes | Escalation run created or replayed idempotently. |
| `escalation_run.viewed` | `escalation_run` | Yes | Escalation timeline viewed. |
| `escalation.action_attempted` | `escalation_action` | Yes | Message/call/location/action attempt started. |
| `escalation.action_completed` | `escalation_action` | Yes | Provider completion, delivery, answer, or failure recorded. |
| `escalation.acknowledged` | `escalation_run` | Yes | Human acknowledges escalation. |
| `escalation.cancelled` | `escalation_run` | Yes | False alarm or user cancellation. |

### Agent, Channels, and Tools

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `agent.message_received` | `message` | Yes | In-app/channel message accepted into a patient conversation. |
| `agent.answer_generated` | `message` | Yes | Agent response generated. |
| `agent.tool_called` | `agent_tool_call` | Maybe | Tool request created; PHI true when tool reads/writes PHI. |
| `agent.tool_denied` | `agent_tool_call` | Maybe | Policy denies tool call. |
| `message.sent` | `message` | Yes | Push/WhatsApp/Telegram/SMS/email sent. |
| `message.delivery_updated` | `message` | Yes | Provider receipt processed. |
| `call.placed` | `escalation_action` | Yes | Voice call started. Must include AI disclosure script ID. |
| `call.completed` | `escalation_action` | Yes | Voice provider completion or transcript summary persisted. |
| `webhook.whatsapp_received` | `webhook_event` | Maybe | WhatsApp webhook verified and accepted. |
| `webhook.telegram_received` | `webhook_event` | Maybe | Telegram webhook verified and accepted. |
| `webhook.voice_received` | `webhook_event` | Maybe | Voice provider webhook verified and accepted. |

### Admin, Security, and Operations

| Action | Resource | PHI | When |
| --- | --- | --- | --- |
| `admin.break_glass_started` | `patient_profile` | Yes | Admin elevates to inspect PHI. Requires reason and MFA. |
| `admin.break_glass_ended` | `patient_profile` | Yes | Admin elevation ends. |
| `audit_logs.viewed` | `audit_log` | Maybe | Audit log viewed. PHI true when patient scoped. |
| `audit_logs.exported` | `audit_log` | Maybe | Audit export generated. |
| `risk_rule.changed` | `risk_rule` | No | Risk rule changed. Critical rules require reviewer metadata. |
| `dead_letter.reviewed` | `outbox_event` | Maybe | Dead-letter event inspected or replayed. |
| `security.webhook_signature_denied` | `webhook_event` | No | Invalid webhook signature rejected. |
| `security.unauthorized_patient_access` | `authorization` | Maybe | Actor attempted unauthorized patient access. |

## Redaction Rules

Audit metadata may include IDs, route names, permission names, status values, counts, provider status codes, and policy decisions. It must not include:

- Raw document text or images.
- Full observation payloads from devices.
- Full LLM prompts or completions containing PHI.
- Secrets, tokens, signed URLs, webhook signatures, or provider credentials.
- Full phone numbers unless necessary for incident review; prefer masked form.

## Hash Chain

For production hardening, compute:

```text
entry_hash = sha256(previous_hash || canonical_json(audit_row_without_hashes))
```

Store the last hash in a separate tamper-evident location or log stream. Hash-chain validation should be part of incident review and audit export tests.
