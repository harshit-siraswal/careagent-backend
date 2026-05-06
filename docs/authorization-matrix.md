# Backend Authorization Matrix

## Authorization Model

Authentication is delegated to Firebase Auth, Auth0, Cognito, or another configured provider. `POST /auth/session` verifies the provider token, resolves `auth_identities.provider + provider_subject`, and returns a CareAgent API token with:

- `sub`: `user_accounts.id`
- `role`: one of `patient`, `caretaker`, `doctor`, `nurse`, `admin`
- `mfa`: authentication assurance state
- `session_id` and `request_id` correlation values

Authorization is a two-part decision:

1. Role gate: the actor role must be eligible for the route.
2. Patient scope gate: any PHI route must resolve a patient and verify either patient ownership or an active `patient_access_grants` row with the required permission.

Consent gates are evaluated after RBAC and before side effects. RBAC answers "may this actor access this patient context?" Consent answers "may this data/action/channel be used for this purpose right now?"

## Permission Strings

Use exact strings in `patient_access_grants.permissions`.

| Permission | Allows |
| --- | --- |
| `patient:read` | Read patient demographics and non-admin profile state. |
| `patient:write` | Update patient profile. |
| `care_team:read` | View care team, contacts, and access grants. |
| `care_team:write` | Add, update, revoke care team members and grants. |
| `consent:read` | View current consent grants and ledger. |
| `consent:write` | Grant or revoke consent. Normally patient-only except admin support with explicit reason. |
| `devices:read` | View devices and connection state. |
| `devices:write` | Register/update devices and connection state. |
| `observations:read` | Query vitals and observations. |
| `observations:write` | Ingest observations. Usually patient app, device connector, or system worker. |
| `documents:read` | View document metadata, processing status, and extracted facts. Raw download requires clean malware scan. |
| `documents:write` | Create upload sessions, review facts, and manage document state. |
| `medicines:read` | View medicines, schedules, and dose history. |
| `medicines:write` | Create schedules and record dose events. |
| `risk:read` | View risk events. |
| `risk:write` | Create/update risk events. Usually risk engine or admin only. |
| `alerts:read` | View alerts. |
| `alerts:write` | Acknowledge, resolve, or assign alerts. |
| `escalation:read` | View escalation policies, runs, and action timelines. |
| `escalation:write` | Configure policies or start escalation runs. |
| `agent:read` | Read conversations, messages, and tool-call history. |
| `agent:write` | Send agent messages. |
| `agent:tool_call` | Execute approved agent tools through policy middleware. |
| `audit:read` | View patient-scoped audit logs. |
| `patient:*` | Break-glass full patient permission. Admin only; requires reason and audit. |

## Default Role Profiles

| Role | Default scope | Notes |
| --- | --- | --- |
| Patient | Own `patient_profiles.account_id` | Full self-management unless consent has been revoked for a feature. |
| Caretaker | Granted patients only | Usually read profile/vitals/doc summary, acknowledge alerts, receive escalation. Writes need explicit grant. |
| Doctor | Granted patients only | Usually read medical data, acknowledge alerts, add notes later. No emergency side effects without consent/policy. |
| Nurse | Granted patients only | Operational care role: device/medicine/alert workflows where granted. |
| Admin | Platform scope | No blanket PHI read in normal support. PHI access requires break-glass reason, MFA, and audit. |

## Route Matrix

| Route | Patient | Caretaker | Doctor | Nurse | Admin | Permission | PHI audit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /auth/session` | Yes | Yes | Yes | Yes | Yes | Provider token | `auth.session_created` |
| `GET /me` | Yes | Yes | Yes | Yes | Yes | Self | `auth.me_viewed` |
| `POST /patients` | Own | No | No | No | Yes | `patient:write` | `patient.profile_created` |
| `GET /patients` | Own summary | Granted | Granted | Granted | Support scoped | `patient:read` | `patient.roster_viewed` |
| `GET /patients/{patient_id}` | Own | Granted | Granted | Granted | Break-glass | `patient:read` | `patient.profile_viewed` |
| `PATCH /patients/{patient_id}` | Own | If granted | No default | If granted | Break-glass | `patient:write` | `patient.profile_updated` |
| `GET /patients/{patient_id}/care-team` | Own | If granted | If granted | If granted | Break-glass | `care_team:read` | `care_team.viewed` |
| `POST /patients/{patient_id}/care-team` | Own | If granted | No default | If granted | Break-glass | `care_team:write` | `care_team.member_added` |
| `GET /patients/{patient_id}/consents` | Own | If granted | If granted | If granted | Break-glass | `consent:read` | `consent.viewed` |
| `POST /patients/{patient_id}/consents` | Own | No default | No default | No default | Break-glass | `consent:write` | `consent.granted` |
| `POST /patients/{patient_id}/consents/{consent_id}/revoke` | Own | No default | No default | No default | Break-glass | `consent:write` | `consent.revoked` |
| `GET /device-catalog` | Public | Public | Public | Public | Public | None | None |
| `GET /patients/{patient_id}/devices` | Own | Granted | Granted | Granted | Break-glass | `devices:read` | `devices.viewed` |
| `POST /patients/{patient_id}/devices` | Own | If granted | No default | If granted | Break-glass | `devices:write` | `device.registered` |
| `GET /patients/{patient_id}/observations` | Own | Granted | Granted | Granted | Break-glass | `observations:read` | `observations.queried` |
| `POST /patients/{patient_id}/observations` | Own/system | No default | No default | If granted | System/admin | `observations:write` | `observation.created` |
| `GET /patients/{patient_id}/vitals/latest` | Own | Granted | Granted | Granted | Break-glass | `observations:read` | `vitals.latest_viewed` |
| `GET /patients/{patient_id}/documents` | Own | Granted | Granted | Granted | Break-glass | `documents:read` | `documents.list_viewed` |
| `POST /patients/{patient_id}/documents` | Own | If granted | If granted | If granted | Break-glass | `documents:write` | `document.upload_session_created` |
| `GET /patients/{patient_id}/documents/{document_id}` | Own | Granted | Granted | Granted | Break-glass | `documents:read` | `document.viewed` |
| `GET /patients/{patient_id}/documents/{document_id}/status` | Own | Granted | Granted | Granted | Break-glass | `documents:read` | `document.status_viewed` |
| `POST /patients/{patient_id}/documents/{document_id}/review` | Own | If granted | If granted | If granted | Break-glass | `documents:write` | `document.extraction_reviewed` |
| `POST /patients/{patient_id}/questions` | Own | Granted | Granted | Granted | Break-glass | `documents:read` | `document.question_answered` |
| `GET /patients/{patient_id}/medicines` | Own | Granted | Granted | Granted | Break-glass | `medicines:read` | `medicines.viewed` |
| `POST /patients/{patient_id}/medicines` | Own | If granted | If granted | If granted | Break-glass | `medicines:write` | `medicine.created` |
| `GET /patients/{patient_id}/medicine-schedule` | Own | Granted | Granted | Granted | Break-glass | `medicines:read` | `medicine_schedule.viewed` |
| `POST /patients/{patient_id}/medicine-schedule` | Own | If granted | If granted | If granted | Break-glass | `medicines:write` | `medicine_schedule.upserted` |
| `POST /patients/{patient_id}/dose-events` | Own | If granted | No default | If granted | Break-glass | `medicines:write` | `medicine_dose.recorded` |
| `POST /patients/{patient_id}/risk-events` | System | No default | No default | No default | Admin/system | `risk:write` | `risk_event.created` |
| `GET /patients/{patient_id}/alerts` | Own | Granted | Granted | Granted | Break-glass | `alerts:read` | `alerts.viewed` |
| `POST /risk-events/{risk_event_id}/acknowledge` | Own | Granted | Granted | Granted | Break-glass | `alerts:write` | `risk_event.acknowledged` |
| `POST /risk-events/{risk_event_id}/escalate` | Own/system | If granted | If granted | If granted | System/admin | `escalation:write` | `escalation.started` |
| `GET /patients/{patient_id}/escalation-policies` | Own | If granted | If granted | If granted | Break-glass | `escalation:read` | `escalation_policies.viewed` |
| `POST /patients/{patient_id}/escalation-policies` | Own | No default | If granted | If granted | Break-glass | `escalation:write` | `escalation_policy.created` |
| `GET /escalation-runs/{escalation_run_id}` | Own | Granted | Granted | Granted | Break-glass | `escalation:read` | `escalation_run.viewed` |
| `POST /agent/messages` | Own | Granted | Granted | Granted | Break-glass | `agent:write` | `agent.message_received` |
| `POST /agent/tools/{tool_name}` | Agent/system | Agent/system | Agent/system | Agent/system | Agent/system | `agent:tool_call` plus tool-specific permission | `agent.tool_called` |
| `POST /webhooks/*` | Provider only | Provider only | Provider only | Provider only | Provider only | Signature verification | `webhook.*_received` |
| `GET /patients/{patient_id}/audit-logs` | Own | No default | No default | No default | Break-glass | `audit:read` | `audit_logs.viewed` |

## Required Decision Flow

1. Verify token and MFA requirements.
2. Resolve actor account and role.
3. Resolve patient scope from the path or from the resource loaded by ID.
4. Reject ambiguous patient scope before querying PHI.
5. Check role eligibility.
6. Check active patient grant or patient ownership.
7. Check consent for channel/action/data type.
8. For idempotent routes, reserve or replay `idempotency_keys`.
9. Perform the action in one transaction where possible.
10. Write audit event before returning PHI or after a denied PHI attempt.

Denied requests for PHI routes still create an audit row with `outcome = denied` and the matched `patient_id` when known.
