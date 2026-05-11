from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from threading import RLock
from typing import Any, Protocol, TypeVar
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.request_context import get_database_actor_context
from app.schemas import (
    Alert,
    ConsentGrant,
    ConsentGrantRequest,
    DoseEventCreateRequest,
    DocumentDetailResponse,
    DocumentProcessingStatus,
    DocumentUploadInitRequest,
    DocumentUploadInitResponse,
    EscalationAction,
    EscalationPolicy,
    EscalationPolicyCreateRequest,
    EscalationRun,
    EscalationStartRequest,
    ExtractedMedicalFact,
    LatestVitalsResponse,
    MedicalDocument,
    Medicine,
    MedicineCreateRequest,
    MedicineDoseEvent,
    MedicineSchedule,
    MedicineScheduleUpsertRequest,
    Observation,
    ObservationBatchCreateRequest,
    ObservationBatchCreateResponse,
    PatientCreateRequest,
    PatientProfile,
    PatientSummary,
    RiskEvent,
    RiskEventCreateRequest,
    UploadTarget,
)
from app.schemas.common import VitalReading, utcnow


T = TypeVar("T")


@dataclass(frozen=True)
class ActorAccount:
    id: UUID
    role: str = "patient"
    patient_id: UUID | None = None


class CareRepository(Protocol):
    def reset(self) -> None: ...

    def get_or_create_account_for_firebase(
        self,
        *,
        subject: str,
        email: str | None,
        display_name: str | None,
        claims: dict[str, Any],
    ) -> ActorAccount: ...

    def list_actor_grants(self, account_id: UUID) -> list[dict[str, Any]]: ...

    def account_patient_id(self, account_id: UUID) -> UUID | None: ...

    def record_audit_event(self, event: Any) -> None: ...

    def list_audit_logs(self, patient_id: UUID, limit: int = 50) -> list[dict[str, Any]]: ...

    def create_patient(self, body: PatientCreateRequest, account_id: UUID) -> PatientProfile: ...

    def list_patients(self, scoped_patient_id: UUID | None = None) -> list[PatientSummary]: ...

    def get_patient(self, patient_id: UUID) -> PatientProfile | None: ...

    def update_patient(self, patient_id: UUID, updates: dict) -> PatientProfile | None: ...

    def grant_consent(self, patient_id: UUID, body: ConsentGrantRequest) -> ConsentGrant: ...

    def list_consents(self, patient_id: UUID) -> list[ConsentGrant]: ...

    def get_consent(self, patient_id: UUID, consent_id: UUID) -> ConsentGrant | None: ...

    def revoke_consent(self, patient_id: UUID, consent_id: UUID) -> ConsentGrant | None: ...

    def create_medicine(self, patient_id: UUID, body: MedicineCreateRequest) -> Medicine: ...

    def list_medicines(self, patient_id: UUID) -> list[Medicine]: ...

    def get_medicine(self, patient_id: UUID, medicine_id: UUID) -> Medicine | None: ...

    def upsert_medicine_schedule(self, patient_id: UUID, body: MedicineScheduleUpsertRequest) -> MedicineSchedule: ...

    def list_medicine_schedules(self, patient_id: UUID) -> list[MedicineSchedule]: ...

    def record_dose_event(self, patient_id: UUID, body: DoseEventCreateRequest) -> MedicineDoseEvent: ...

    def create_observations(self, patient_id: UUID, body: ObservationBatchCreateRequest) -> ObservationBatchCreateResponse: ...

    def list_observations(
        self,
        patient_id: UUID,
        *,
        metric_code: str | None = None,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
        limit: int = 50,
    ) -> list[Observation]: ...

    def get_observation(self, patient_id: UUID, observation_id: UUID) -> Observation | None: ...

    def latest_vitals(self, patient_id: UUID) -> LatestVitalsResponse: ...

    def list_documents(self, patient_id: UUID) -> list[MedicalDocument]: ...

    def init_document_upload(
        self,
        patient_id: UUID,
        body: DocumentUploadInitRequest,
        *,
        idempotency_key: str,
        actor_id: UUID | None = None,
    ) -> DocumentUploadInitResponse: ...

    def get_document(self, patient_id: UUID, document_id: UUID) -> DocumentDetailResponse | None: ...

    def document_status(self, patient_id: UUID, document_id: UUID) -> DocumentProcessingStatus | None: ...

    def review_document(
        self,
        patient_id: UUID,
        document_id: UUID,
        facts: list[dict[str, Any]],
    ) -> DocumentDetailResponse | None: ...

    def create_risk_event(self, patient_id: UUID, body: RiskEventCreateRequest) -> RiskEvent: ...

    def list_alerts(self, patient_id: UUID) -> list[Alert]: ...

    def acknowledge_risk_event(self, risk_event_id: UUID, patient_id: UUID) -> RiskEvent | None: ...

    def list_escalation_policies(self, patient_id: UUID) -> list[EscalationPolicy]: ...

    def create_escalation_policy(
        self,
        patient_id: UUID,
        body: EscalationPolicyCreateRequest,
        actor_id: UUID | None = None,
    ) -> EscalationPolicy: ...

    def start_escalation(
        self,
        risk_event_id: UUID,
        patient_id: UUID,
        body: EscalationStartRequest,
        *,
        idempotency_key: str,
        actor_id: UUID | None = None,
    ) -> EscalationRun: ...

    def get_escalation_run(self, escalation_run_id: UUID, patient_id: UUID) -> EscalationRun | None: ...

    def acknowledge_escalation_run(
        self,
        escalation_run_id: UUID,
        patient_id: UUID,
        actor_id: UUID | None = None,
        note: str | None = None,
    ) -> EscalationRun | None: ...


class InMemoryCareRepository:
    """Process-local repository for tests and early client integration."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._accounts: dict[UUID, ActorAccount] = {}
            self._firebase_identities: dict[str, UUID] = {}
            self._audit_events: list[Any] = []
            self._patients: dict[UUID, PatientProfile] = {}
            self._consents: dict[UUID, ConsentGrant] = {}
            self._medicines: dict[UUID, Medicine] = {}
            self._medicine_schedules: dict[UUID, MedicineSchedule] = {}
            self._dose_events: dict[UUID, MedicineDoseEvent] = {}
            self._observations: dict[UUID, Observation] = {}
            self._documents: dict[UUID, MedicalDocument] = {}
            self._document_facts: dict[UUID, list[ExtractedMedicalFact]] = {}
            self._risk_events: dict[UUID, RiskEvent] = {}
            self._alerts: dict[UUID, Alert] = {}
            self._escalation_policies: dict[UUID, EscalationPolicy] = {}
            self._escalation_runs: dict[UUID, EscalationRun] = {}

    def get_or_create_account_for_firebase(
        self,
        *,
        subject: str,
        email: str | None,
        display_name: str | None,
        claims: dict[str, Any],
    ) -> ActorAccount:
        with self._lock:
            existing_id = self._firebase_identities.get(subject)
            if existing_id is not None:
                return self._account_with_patient(existing_id)
            account = ActorAccount(id=uuid4())
            self._accounts[account.id] = account
            self._firebase_identities[subject] = account.id
            return account

    def list_actor_grants(self, account_id: UUID) -> list[dict[str, Any]]:
        return []

    def account_patient_id(self, account_id: UUID) -> UUID | None:
        with self._lock:
            return next(
                (patient.id for patient in self._patients.values() if patient.account_id == account_id),
                None,
            )

    def record_audit_event(self, event: Any) -> None:
        with self._lock:
            self._audit_events.append(event)

    def list_audit_logs(self, patient_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            events = [
                event.model_dump(mode="json")
                for event in self._audit_events
                if event.patient_id == patient_id
            ]
            return events[-max(1, min(limit, 500)) :][::-1]

    def _account_with_patient(self, account_id: UUID) -> ActorAccount:
        account = self._accounts.get(account_id, ActorAccount(id=account_id))
        patient_id = next(
            (patient.id for patient in self._patients.values() if patient.account_id == account_id),
            None,
        )
        return ActorAccount(id=account.id, role=account.role, patient_id=patient_id)

    def create_patient(self, body: PatientCreateRequest, account_id: UUID) -> PatientProfile:
        patient = PatientProfile(**body.model_dump(), account_id=account_id)
        with self._lock:
            self._accounts.setdefault(account_id, ActorAccount(id=account_id))
            self._patients[patient.id] = patient
            return _copy(patient)

    def list_patients(self, scoped_patient_id: UUID | None = None) -> list[PatientSummary]:
        with self._lock:
            patients = list(self._patients.values())
            if scoped_patient_id is not None:
                patients = [patient for patient in patients if patient.id == scoped_patient_id]
            return [
                PatientSummary(
                    id=patient.id,
                    full_name=patient.full_name,
                    primary_language=patient.primary_language,
                )
                for patient in patients
            ]

    def get_patient(self, patient_id: UUID) -> PatientProfile | None:
        with self._lock:
            patient = self._patients.get(patient_id)
            return _copy(patient) if patient else None

    def update_patient(self, patient_id: UUID, updates: dict) -> PatientProfile | None:
        with self._lock:
            patient = self._patients.get(patient_id)
            if patient is None:
                return None
            updated = patient.model_copy(update=updates)
            self._patients[patient_id] = updated
            return _copy(updated)

    def grant_consent(self, patient_id: UUID, body: ConsentGrantRequest) -> ConsentGrant:
        consent = ConsentGrant(**body.model_dump(), patient_id=patient_id)
        with self._lock:
            self._consents[consent.id] = consent
            return _copy(consent)

    def list_consents(self, patient_id: UUID) -> list[ConsentGrant]:
        with self._lock:
            return [_copy(consent) for consent in self._consents.values() if consent.patient_id == patient_id]

    def get_consent(self, patient_id: UUID, consent_id: UUID) -> ConsentGrant | None:
        with self._lock:
            consent = self._consents.get(consent_id)
            if consent is None or consent.patient_id != patient_id:
                return None
            return _copy(consent)

    def revoke_consent(self, patient_id: UUID, consent_id: UUID) -> ConsentGrant | None:
        with self._lock:
            consent = self._consents.get(consent_id)
            if consent is None or consent.patient_id != patient_id:
                return None
            revoked = consent.model_copy(update={"status": "revoked"})
            self._consents[consent_id] = revoked
            return _copy(revoked)

    def create_medicine(self, patient_id: UUID, body: MedicineCreateRequest) -> Medicine:
        medicine = Medicine(**body.model_dump(), patient_id=patient_id)
        with self._lock:
            self._medicines[medicine.id] = medicine
            return _copy(medicine)

    def list_medicines(self, patient_id: UUID) -> list[Medicine]:
        with self._lock:
            return [_copy(medicine) for medicine in self._medicines.values() if medicine.patient_id == patient_id]

    def get_medicine(self, patient_id: UUID, medicine_id: UUID) -> Medicine | None:
        with self._lock:
            medicine = self._medicines.get(medicine_id)
            if medicine is None or medicine.patient_id != patient_id:
                return None
            return _copy(medicine)

    def upsert_medicine_schedule(self, patient_id: UUID, body: MedicineScheduleUpsertRequest) -> MedicineSchedule:
        with self._lock:
            existing = next(
                (
                    schedule
                    for schedule in self._medicine_schedules.values()
                    if schedule.patient_id == patient_id and schedule.medicine_id == body.medicine_id
                ),
                None,
            )
            medicine = self._medicines.get(body.medicine_id)
            schedule_id = existing.id if existing else uuid4()
            schedule = MedicineSchedule(
                **body.model_dump(),
                id=schedule_id,
                patient_id=patient_id,
                medicine=_copy(medicine) if medicine else None,
            )
            self._medicine_schedules[schedule.id] = schedule
            return _copy(schedule)

    def list_medicine_schedules(self, patient_id: UUID) -> list[MedicineSchedule]:
        with self._lock:
            return [
                _copy(schedule)
                for schedule in self._medicine_schedules.values()
                if schedule.patient_id == patient_id
            ]

    def record_dose_event(self, patient_id: UUID, body: DoseEventCreateRequest) -> MedicineDoseEvent:
        dose = MedicineDoseEvent(**body.model_dump(), patient_id=patient_id)
        with self._lock:
            self._dose_events[dose.id] = dose
            return _copy(dose)

    def create_observations(self, patient_id: UUID, body: ObservationBatchCreateRequest) -> ObservationBatchCreateResponse:
        observations = [
            Observation(**observation.model_dump(), patient_id=patient_id)
            for observation in body.observations
        ]
        response = ObservationBatchCreateResponse(accepted_count=len(observations))
        with self._lock:
            for observation in observations:
                self._observations[observation.id] = observation
            return response

    def list_observations(
        self,
        patient_id: UUID,
        *,
        metric_code: str | None = None,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
        limit: int = 50,
    ) -> list[Observation]:
        with self._lock:
            observations = [
                observation
                for observation in self._observations.values()
                if observation.patient_id == patient_id
            ]
            if metric_code is not None:
                observations = [observation for observation in observations if observation.metric_code == metric_code]
            if observed_from is not None:
                observations = [observation for observation in observations if observation.observed_at >= observed_from]
            if observed_to is not None:
                observations = [observation for observation in observations if observation.observed_at <= observed_to]

            safe_limit = min(max(limit, 1), 500)
            observations.sort(key=lambda observation: observation.observed_at, reverse=True)
            return [_copy(observation) for observation in observations[:safe_limit]]

    def get_observation(self, patient_id: UUID, observation_id: UUID) -> Observation | None:
        with self._lock:
            observation = self._observations.get(observation_id)
            if observation is None or observation.patient_id != patient_id:
                return None
            return _copy(observation)

    def latest_vitals(self, patient_id: UUID) -> LatestVitalsResponse:
        with self._lock:
            latest_by_metric: dict[str, Observation] = {}
            for observation in self._observations.values():
                if observation.patient_id != patient_id:
                    continue
                current = latest_by_metric.get(observation.metric_code)
                if current is None or observation.observed_at > current.observed_at:
                    latest_by_metric[observation.metric_code] = observation

            readings = [
                VitalReading(
                    metric_code=observation.metric_code,
                    value=observation.value,
                    unit=observation.unit or "",
                    observed_at=observation.observed_at,
                    source=observation.source_type,
                )
                for observation in sorted(latest_by_metric.values(), key=lambda item: item.metric_code)
            ]
            return LatestVitalsResponse(patient_id=patient_id, readings=readings)

    def list_documents(self, patient_id: UUID) -> list[MedicalDocument]:
        with self._lock:
            return [
                _copy(document)
                for document in self._documents.values()
                if document.patient_id == patient_id
            ]

    def init_document_upload(
        self,
        patient_id: UUID,
        body: DocumentUploadInitRequest,
        *,
        idempotency_key: str,
        actor_id: UUID | None = None,
    ) -> DocumentUploadInitResponse:
        document = MedicalDocument(
            patient_id=patient_id,
            original_filename=body.original_filename,
            file_type=body.file_type,
            document_type=body.document_type_hint,
        )
        with self._lock:
            self._documents[document.id] = document
        upload = UploadTarget(
            url=f"https://object-storage.invalid/{patient_id}/{document.id}/{body.original_filename}",
            headers={"x-careagent-idempotency-key": idempotency_key},
        )
        return DocumentUploadInitResponse(document=document, upload=upload)

    def get_document(self, patient_id: UUID, document_id: UUID) -> DocumentDetailResponse | None:
        with self._lock:
            document = self._documents.get(document_id)
            if document is None or document.patient_id != patient_id:
                return None
            return DocumentDetailResponse(
                document=_copy(document),
                facts=[_copy(fact) for fact in self._document_facts.get(document_id, [])],
            )

    def document_status(self, patient_id: UUID, document_id: UUID) -> DocumentProcessingStatus | None:
        detail = self.get_document(patient_id, document_id)
        if detail is None:
            return None
        document = detail.document
        return DocumentProcessingStatus(
            document_id=document.id,
            malware_scan_status=document.malware_scan_status,
            ocr_status=document.ocr_status,
            extraction_status=document.extraction_status,
        )

    def review_document(
        self,
        patient_id: UUID,
        document_id: UUID,
        facts: list[dict[str, Any]],
    ) -> DocumentDetailResponse | None:
        with self._lock:
            document = self._documents.get(document_id)
            if document is None or document.patient_id != patient_id:
                return None
            reviewed = [
                ExtractedMedicalFact(
                    id=fact["fact_id"],
                    fact_type="reviewed",
                    label="Reviewed fact",
                    value=fact.get("corrected_value") or "reviewed",
                    review_status=fact["review_status"],
                    corrected_value=fact.get("corrected_value"),
                )
                for fact in facts
            ]
            self._document_facts[document_id] = reviewed
            updated = document.model_copy(update={"review_status": "approved"})
            self._documents[document_id] = updated
            return DocumentDetailResponse(document=_copy(updated), facts=[_copy(fact) for fact in reviewed])

    def create_risk_event(self, patient_id: UUID, body: RiskEventCreateRequest) -> RiskEvent:
        risk_event = RiskEvent(**body.model_dump(), patient_id=patient_id)
        alert = Alert(
            patient_id=patient_id,
            risk_event_id=risk_event.id,
            severity=risk_event.severity,
            title=f"{risk_event.severity.title()} risk detected",
            body=risk_event.reason,
        )
        with self._lock:
            self._risk_events[risk_event.id] = risk_event
            self._alerts[alert.id] = alert
            return _copy(risk_event)

    def list_alerts(self, patient_id: UUID) -> list[Alert]:
        with self._lock:
            return [
                _copy(alert)
                for alert in self._alerts.values()
                if alert.patient_id == patient_id
            ]

    def acknowledge_risk_event(self, risk_event_id: UUID, patient_id: UUID) -> RiskEvent | None:
        with self._lock:
            risk_event = self._risk_events.get(risk_event_id)
            if risk_event is None or risk_event.patient_id != patient_id:
                return None
            acknowledged = risk_event.model_copy(
                update={"status": "acknowledged", "acknowledged_at": utcnow()}
            )
            self._risk_events[risk_event_id] = acknowledged
            for alert_id, alert in list(self._alerts.items()):
                if alert.risk_event_id == risk_event_id:
                    self._alerts[alert_id] = alert.model_copy(update={"status": "acknowledged"})
            return _copy(acknowledged)

    def list_escalation_policies(self, patient_id: UUID) -> list[EscalationPolicy]:
        with self._lock:
            return [
                _copy(policy)
                for policy in self._escalation_policies.values()
                if policy.patient_id == patient_id and policy.active
            ]

    def create_escalation_policy(
        self,
        patient_id: UUID,
        body: EscalationPolicyCreateRequest,
        actor_id: UUID | None = None,
    ) -> EscalationPolicy:
        policy = EscalationPolicy(**body.model_dump(), patient_id=patient_id)
        with self._lock:
            self._escalation_policies[policy.id] = policy
            return _copy(policy)

    def start_escalation(
        self,
        risk_event_id: UUID,
        patient_id: UUID,
        body: EscalationStartRequest,
        *,
        idempotency_key: str,
        actor_id: UUID | None = None,
    ) -> EscalationRun:
        with self._lock:
            for run in self._escalation_runs.values():
                if run.risk_event_id == risk_event_id and run.policy_id == body.policy_id:
                    return _copy(run)
            policy = self._escalation_policies.get(body.policy_id)
            run = EscalationRun(
                risk_event_id=risk_event_id,
                patient_id=patient_id,
                policy_id=body.policy_id,
                status="awaiting_ack" if body.simulation_mode else "running",
                outcome="simulation_started" if body.simulation_mode else None,
            )
            if policy:
                run.actions = [
                    EscalationAction(
                        step_order=step.step_order,
                        action_type=step.action_type,
                        channel=step.channel,
                        status="delivered" if body.simulation_mode else "pending",
                        target_contact_id=step.target_contact_id,
                    )
                    for step in policy.steps
                ]
            self._escalation_runs[run.id] = run
            risk_event = self._risk_events.get(risk_event_id)
            if risk_event and risk_event.patient_id == patient_id:
                self._risk_events[risk_event_id] = risk_event.model_copy(update={"status": "escalating"})
            return _copy(run)

    def get_escalation_run(self, escalation_run_id: UUID, patient_id: UUID) -> EscalationRun | None:
        with self._lock:
            run = self._escalation_runs.get(escalation_run_id)
            if run is None or run.patient_id != patient_id:
                return None
            return _copy(run)

    def acknowledge_escalation_run(
        self,
        escalation_run_id: UUID,
        patient_id: UUID,
        actor_id: UUID | None = None,
        note: str | None = None,
    ) -> EscalationRun | None:
        with self._lock:
            run = self._escalation_runs.get(escalation_run_id)
            if run is None or run.patient_id != patient_id:
                return None
            updated = run.model_copy(update={"status": "acknowledged", "outcome": note or "acknowledged"})
            self._escalation_runs[escalation_run_id] = updated
            return _copy(updated)


class PostgresCareRepository:
    """Repository backed by the Supabase/Postgres schema in migrations."""

    def __init__(self, database_url: str, document_bucket: str) -> None:
        self.database_url = database_url
        self.document_bucket = document_bucket
        self._pool: Any | None = None

    def reset(self) -> None:
        return None

    def get_or_create_account_for_firebase(
        self,
        *,
        subject: str,
        email: str | None,
        display_name: str | None,
        claims: dict[str, Any],
    ) -> ActorAccount:
        with self._connect() as conn:
            existing = conn.execute(
                """
                select ua.id, ua.role, pp.id as patient_id
                from auth_identities ai
                join user_accounts ua on ua.id = ai.user_account_id
                left join patient_profiles pp on pp.account_id = ua.id
                where ai.provider = 'firebase' and ai.provider_subject = %s
                """,
                (subject,),
            ).fetchone()
            if existing:
                conn.execute(
                    "update auth_identities set provider_claims = %s, last_login_at = now(), updated_at = now() where provider = 'firebase' and provider_subject = %s",
                    (_json(claims), subject),
                )
                return ActorAccount(id=existing["id"], role=existing["role"], patient_id=existing["patient_id"])

            account = conn.execute(
                """
                insert into user_accounts (email, display_name, role, status)
                values (%s, %s, 'patient', 'active')
                returning id, role
                """,
                (email or f"firebase-{subject}@careagent.local", display_name),
            ).fetchone()
            conn.execute(
                """
                insert into auth_identities (user_account_id, provider, provider_subject, provider_claims, last_login_at)
                values (%s, 'firebase', %s, %s, now())
                """,
                (account["id"], subject, _json(claims)),
            )
            return ActorAccount(id=account["id"], role=account["role"])

    def list_actor_grants(self, account_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select patient_id, role, permissions
                from patient_access_grants
                where grantee_user_account_id = %s
                  and status = 'active'
                  and (expires_at is null or expires_at > now())
                """,
                (account_id,),
            ).fetchall()
            return [
                {
                    "patient_id": row["patient_id"],
                    "role": row["role"],
                    "permissions": list(row["permissions"] or []),
                }
                for row in rows
            ]

    def account_patient_id(self, account_id: UUID) -> UUID | None:
        with self._connect() as conn:
            row = conn.execute(
                "select id from patient_profiles where account_id = %s",
                (account_id,),
            ).fetchone()
            return row["id"] if row else None

    def record_audit_event(self, event: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into audit_logs (
                  id, actor_type, actor_id, actor_user_id, patient_id, action,
                  resource_type, resource_id, outcome, phi_access, reason,
                  request_id, metadata_json, created_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do nothing
                """,
                (
                    event.id,
                    event.actor_type,
                    event.actor_id,
                    event.actor_user_id,
                    event.patient_id,
                    event.action,
                    event.resource_type,
                    event.resource_id,
                    event.outcome,
                    event.phi_access,
                    event.reason,
                    event.request_id,
                    _json(event.metadata_json),
                    event.created_at,
                ),
            )

    def list_audit_logs(self, patient_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select id, action, resource_type, resource_id, outcome, phi_access,
                       reason, request_id, metadata_json, created_at, actor_user_id,
                       patient_id
                from audit_logs
                where patient_id = %s
                order by created_at desc
                limit %s
                """,
                (patient_id, min(max(limit, 1), 500)),
            ).fetchall()
            return [_row_dict(row) for row in rows]

    def create_patient(self, body: PatientCreateRequest, account_id: UUID) -> PatientProfile:
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into patient_profiles (
                  account_id, full_name, date_of_birth, sex, primary_language,
                  address, emergency_location_notes, conditions, allergies,
                  baseline_notes
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    account_id,
                    body.full_name,
                    body.date_of_birth,
                    body.sex,
                    body.primary_language,
                    _json(body.address),
                    body.emergency_location_notes,
                    _json(body.conditions),
                    _json(body.allergies),
                    body.baseline_notes,
                ),
            ).fetchone()
            return _patient(row)

    def list_patients(self, scoped_patient_id: UUID | None = None) -> list[PatientSummary]:
        with self._connect() as conn:
            if scoped_patient_id:
                rows = conn.execute(
                    "select id, full_name, primary_language from patient_profiles where id = %s",
                    (scoped_patient_id,),
                ).fetchall()
            else:
                rows = conn.execute("select id, full_name, primary_language from patient_profiles order by created_at desc").fetchall()
            return [PatientSummary(**_row_dict(row)) for row in rows]

    def get_patient(self, patient_id: UUID) -> PatientProfile | None:
        with self._connect() as conn:
            row = conn.execute("select * from patient_profiles where id = %s", (patient_id,)).fetchone()
            return _patient(row) if row else None

    def update_patient(self, patient_id: UUID, updates: dict) -> PatientProfile | None:
        if not updates:
            return self.get_patient(patient_id)
        allowed = {
            "full_name",
            "date_of_birth",
            "sex",
            "primary_language",
            "address",
            "emergency_location_notes",
            "conditions",
            "allergies",
            "baseline_notes",
        }
        fields = [field for field in updates if field in allowed]
        assignments = ", ".join(f"{field} = %s" for field in fields)
        values = [_json(updates[field]) if field in {"address", "conditions", "allergies"} else updates[field] for field in fields]
        with self._connect() as conn:
            row = conn.execute(
                f"update patient_profiles set {assignments}, updated_at = now() where id = %s returning *",
                (*values, patient_id),
            ).fetchone()
            return _patient(row) if row else None

    def grant_consent(self, patient_id: UUID, body: ConsentGrantRequest) -> ConsentGrant:
        with self._connect() as conn:
            patient = conn.execute("select account_id from patient_profiles where id = %s", (patient_id,)).fetchone()
            subject_user_id = patient["account_id"] if patient else None
            row = conn.execute(
                """
                insert into consent_grants (
                  patient_id, subject_user_id, consent_type, scope, channel,
                  granted_to_user_id, granted_to_contact_id, expires_at,
                  consent_text_version
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    patient_id,
                    subject_user_id,
                    body.consent_type,
                    _json(body.scope),
                    body.channel,
                    body.granted_to_user_id,
                    body.granted_to_contact_id,
                    body.expires_at,
                    body.consent_text_version,
                ),
            ).fetchone()
            return _consent(row, reason=body.reason)

    def list_consents(self, patient_id: UUID) -> list[ConsentGrant]:
        with self._connect() as conn:
            rows = conn.execute("select * from consent_grants where patient_id = %s order by granted_at desc", (patient_id,)).fetchall()
            return [_consent(row) for row in rows]

    def get_consent(self, patient_id: UUID, consent_id: UUID) -> ConsentGrant | None:
        with self._connect() as conn:
            row = conn.execute("select * from consent_grants where patient_id = %s and id = %s", (patient_id, consent_id)).fetchone()
            return _consent(row) if row else None

    def revoke_consent(self, patient_id: UUID, consent_id: UUID) -> ConsentGrant | None:
        with self._connect() as conn:
            row = conn.execute(
                "update consent_grants set status = 'revoked', revoked_at = now(), updated_at = now() where patient_id = %s and id = %s returning *",
                (patient_id, consent_id),
            ).fetchone()
            return _consent(row) if row else None

    def create_medicine(self, patient_id: UUID, body: MedicineCreateRequest) -> Medicine:
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into medicines (patient_id, name, normalized_name, strength, form, instructions, source_document_id)
                values (%s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (patient_id, body.name, body.normalized_name, body.strength, body.form, body.instructions, body.source_document_id),
            ).fetchone()
            return _medicine(row)

    def list_medicines(self, patient_id: UUID) -> list[Medicine]:
        with self._connect() as conn:
            rows = conn.execute("select * from medicines where patient_id = %s and active = true order by name", (patient_id,)).fetchall()
            return [_medicine(row) for row in rows]

    def get_medicine(self, patient_id: UUID, medicine_id: UUID) -> Medicine | None:
        with self._connect() as conn:
            row = conn.execute("select * from medicines where patient_id = %s and id = %s", (patient_id, medicine_id)).fetchone()
            return _medicine(row) if row else None

    def upsert_medicine_schedule(self, patient_id: UUID, body: MedicineScheduleUpsertRequest) -> MedicineSchedule:
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into medicine_schedules (
                  medicine_id, patient_id, dose, route, scheduled_times,
                  start_date, end_date, with_food, special_instructions,
                  review_status
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    body.medicine_id,
                    patient_id,
                    body.dose,
                    body.route,
                    _json([time.model_dump(mode="json") for time in body.scheduled_times]),
                    body.start_date,
                    body.end_date,
                    body.with_food,
                    body.special_instructions,
                    body.review_status,
                ),
            ).fetchone()
            return _schedule(row, self.get_medicine(patient_id, body.medicine_id))

    def list_medicine_schedules(self, patient_id: UUID) -> list[MedicineSchedule]:
        with self._connect() as conn:
            rows = conn.execute("select * from medicine_schedules where patient_id = %s order by start_date desc", (patient_id,)).fetchall()
            return [_schedule(row, self.get_medicine(patient_id, row["medicine_id"])) for row in rows]

    def record_dose_event(self, patient_id: UUID, body: DoseEventCreateRequest) -> MedicineDoseEvent:
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into medicine_dose_events (
                  schedule_id, patient_id, scheduled_at, status, source_channel,
                  idempotency_key, notes
                )
                values (%s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    body.schedule_id,
                    patient_id,
                    body.scheduled_at,
                    body.status,
                    body.source_channel,
                    body.idempotency_key,
                    body.notes,
                ),
            ).fetchone()
            return _dose_event(row)

    def create_observations(self, patient_id: UUID, body: ObservationBatchCreateRequest) -> ObservationBatchCreateResponse:
        with self._connect() as conn:
            for observation in body.observations:
                value = observation.value
                numeric = value if isinstance(value, int | float) and not isinstance(value, bool) else None
                text = None if numeric is not None else str(value)
                conn.execute(
                    """
                    insert into observations (
                      patient_id, device_id, metric_code, value_numeric, value_text,
                      unit, observed_at, source_type, reliability_tier, confidence
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        patient_id,
                        observation.device_id,
                        observation.metric_code,
                        numeric,
                        text,
                        observation.unit,
                        observation.observed_at,
                        observation.source_type,
                        observation.reliability_tier,
                        observation.confidence,
                    ),
                )
            return ObservationBatchCreateResponse(accepted_count=len(body.observations))

    def list_observations(
        self,
        patient_id: UUID,
        *,
        metric_code: str | None = None,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
        limit: int = 50,
    ) -> list[Observation]:
        clauses = ["patient_id = %s"]
        values: list[Any] = [patient_id]
        if metric_code:
            clauses.append("metric_code = %s")
            values.append(metric_code)
        if observed_from:
            clauses.append("observed_at >= %s")
            values.append(observed_from)
        if observed_to:
            clauses.append("observed_at <= %s")
            values.append(observed_to)
        values.append(min(max(limit, 1), 500))
        with self._connect() as conn:
            rows = conn.execute(
                f"select * from observations where {' and '.join(clauses)} order by observed_at desc limit %s",
                tuple(values),
            ).fetchall()
            return [_observation(row) for row in rows]

    def get_observation(self, patient_id: UUID, observation_id: UUID) -> Observation | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from observations where patient_id = %s and id = %s",
                (patient_id, observation_id),
            ).fetchone()
            return _observation(row) if row else None

    def latest_vitals(self, patient_id: UUID) -> LatestVitalsResponse:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select distinct on (metric_code) *
                from observations
                where patient_id = %s
                order by metric_code, observed_at desc
                """,
                (patient_id,),
            ).fetchall()
            readings = [
                VitalReading(
                    metric_code=row["metric_code"],
                    value=_observation_value(row),
                    unit=row["unit"] or "",
                    observed_at=row["observed_at"],
                    source=row["source_type"],
                )
                for row in rows
            ]
            return LatestVitalsResponse(patient_id=patient_id, readings=readings)

    def list_documents(self, patient_id: UUID) -> list[MedicalDocument]:
        with self._connect() as conn:
            rows = conn.execute("select * from medical_documents where patient_id = %s order by created_at desc", (patient_id,)).fetchall()
            return [_document(row) for row in rows]

    def init_document_upload(
        self,
        patient_id: UUID,
        body: DocumentUploadInitRequest,
        *,
        idempotency_key: str,
        actor_id: UUID | None = None,
    ) -> DocumentUploadInitResponse:
        object_key = f"{patient_id}/{uuid4()}-{body.original_filename}"
        file_uri = f"s3://{self.document_bucket}/{object_key}"
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into medical_documents (
                  patient_id, uploaded_by, upload_channel, object_bucket,
                  object_key, file_uri, file_type, document_type,
                  original_filename, file_size_bytes, sha256,
                  ocr_status, extraction_status
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'blocked', 'blocked')
                returning *
                """,
                (
                    patient_id,
                    actor_id,
                    body.upload_channel or "in_app",
                    self.document_bucket,
                    object_key,
                    file_uri,
                    body.file_type,
                    body.document_type_hint,
                    body.original_filename,
                    body.file_size_bytes,
                    body.sha256,
                ),
            ).fetchone()
            return DocumentUploadInitResponse(
                document=_document(row),
                upload=UploadTarget(url=file_uri, headers={"x-careagent-idempotency-key": idempotency_key}),
            )

    def get_document(self, patient_id: UUID, document_id: UUID) -> DocumentDetailResponse | None:
        with self._connect() as conn:
            document = conn.execute("select * from medical_documents where patient_id = %s and id = %s", (patient_id, document_id)).fetchone()
            if not document:
                return None
            facts = conn.execute("select * from extracted_medical_facts where patient_id = %s and document_id = %s", (patient_id, document_id)).fetchall()
            return DocumentDetailResponse(document=_document(document), facts=[_fact(row) for row in facts])

    def document_status(self, patient_id: UUID, document_id: UUID) -> DocumentProcessingStatus | None:
        detail = self.get_document(patient_id, document_id)
        if detail is None:
            return None
        document = detail.document
        return DocumentProcessingStatus(
            document_id=document.id,
            malware_scan_status=document.malware_scan_status,
            ocr_status=document.ocr_status,
            extraction_status=document.extraction_status,
        )

    def review_document(
        self,
        patient_id: UUID,
        document_id: UUID,
        facts: list[dict[str, Any]],
    ) -> DocumentDetailResponse | None:
        with self._connect() as conn:
            if not conn.execute("select id from medical_documents where patient_id = %s and id = %s", (patient_id, document_id)).fetchone():
                return None
            for fact in facts:
                conn.execute(
                    """
                    insert into extracted_medical_facts (
                      id, document_id, patient_id, fact_type, label, value,
                      confidence, review_status, corrected_value
                    )
                    values (%s, %s, %s, 'reviewed', 'Reviewed fact', %s, 1.0, %s, %s)
                    on conflict (id) do update set
                      review_status = excluded.review_status,
                      corrected_value = excluded.corrected_value,
                      updated_at = now()
                    """,
                    (
                        fact["fact_id"],
                        document_id,
                        patient_id,
                        fact.get("corrected_value") or "reviewed",
                        fact["review_status"],
                        fact.get("corrected_value"),
                    ),
                )
            conn.execute("update medical_documents set review_status = 'approved', updated_at = now() where id = %s", (document_id,))
        return self.get_document(patient_id, document_id)

    def create_risk_event(self, patient_id: UUID, body: RiskEventCreateRequest) -> RiskEvent:
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into risk_events (patient_id, severity, confidence, reason, evidence_json, rule_id)
                values (%s, %s, %s, %s, %s, %s)
                returning *
                """,
                (patient_id, body.severity, body.confidence, body.reason, _json(body.evidence), body.rule_id),
            ).fetchone()
            conn.execute(
                """
                insert into alerts (patient_id, risk_event_id, severity, title, body)
                values (%s, %s, %s, %s, %s)
                """,
                (patient_id, row["id"], body.severity, f"{body.severity.title()} risk detected", body.reason),
            )
            return _risk_event(row, recommended_action=body.recommended_action)

    def list_alerts(self, patient_id: UUID) -> list[Alert]:
        with self._connect() as conn:
            rows = conn.execute("select * from alerts where patient_id = %s order by created_at desc", (patient_id,)).fetchall()
            return [Alert(**_row_dict(row)) for row in rows]

    def acknowledge_risk_event(self, risk_event_id: UUID, patient_id: UUID) -> RiskEvent | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                update risk_events
                set status = 'acknowledged', acknowledged_at = now(), updated_at = now()
                where id = %s and patient_id = %s
                returning *
                """,
                (risk_event_id, patient_id),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "update alerts set status = 'acknowledged', acknowledged_at = now(), updated_at = now() where risk_event_id = %s",
                (risk_event_id,),
            )
            return _risk_event(row)

    def list_escalation_policies(self, patient_id: UUID) -> list[EscalationPolicy]:
        with self._connect() as conn:
            rows = conn.execute("select * from escalation_policies where patient_id = %s and active = true", (patient_id,)).fetchall()
            return [_policy(conn, row) for row in rows]

    def create_escalation_policy(
        self,
        patient_id: UUID,
        body: EscalationPolicyCreateRequest,
        actor_id: UUID | None = None,
    ) -> EscalationPolicy:
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into escalation_policies (
                  patient_id, name, severity_trigger,
                  patient_confirmation_timeout_seconds, emergency_enabled,
                  location_sharing_enabled, simulation_mode, created_by
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    patient_id,
                    body.name,
                    body.severity_trigger,
                    body.patient_confirmation_timeout_seconds,
                    body.emergency_enabled,
                    body.location_sharing_enabled,
                    body.simulation_mode,
                    actor_id,
                ),
            ).fetchone()
            for step in body.steps:
                conn.execute(
                    """
                    insert into escalation_policy_steps (
                      policy_id, step_order, action_type, target_contact_id,
                      target_role, channel, template_id, timeout_seconds,
                      retry_count, include_location
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["id"],
                        step.step_order,
                        step.action_type,
                        step.target_contact_id,
                        step.target_role or "family",
                        step.channel,
                        step.template_id,
                        step.timeout_seconds or 60,
                        step.retry_count or 0,
                        step.include_location or False,
                    ),
                )
            return _policy(conn, row)

    def start_escalation(
        self,
        risk_event_id: UUID,
        patient_id: UUID,
        body: EscalationStartRequest,
        *,
        idempotency_key: str,
        actor_id: UUID | None = None,
    ) -> EscalationRun:
        with self._connect() as conn:
            existing = conn.execute(
                "select * from escalation_runs where idempotency_key = %s or (risk_event_id = %s and policy_id = %s)",
                (idempotency_key, risk_event_id, body.policy_id),
            ).fetchone()
            if existing:
                return _run(conn, existing)
            row = conn.execute(
                """
                insert into escalation_runs (
                  risk_event_id, patient_id, policy_id, status, idempotency_key,
                  requested_by, requested_by_user_id, outcome, metadata_json
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    risk_event_id,
                    patient_id,
                    body.policy_id,
                    "awaiting_ack" if body.simulation_mode else "running",
                    idempotency_key,
                    body.requested_by,
                    actor_id,
                    "simulation_started" if body.simulation_mode else None,
                    _json({"simulation": body.simulation_mode, "reason": body.reason}),
                ),
            ).fetchone()
            steps = conn.execute(
                "select * from escalation_policy_steps where policy_id = %s order by step_order",
                (body.policy_id,),
            ).fetchall()
            for step in steps:
                conn.execute(
                    """
                    insert into escalation_actions (
                      escalation_run_id, step_id, step_order, action_type,
                      target_contact_id, channel, template_id, status
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["id"],
                        step["id"],
                        step["step_order"],
                        step["action_type"],
                        step["target_contact_id"],
                        step["channel"],
                        step["template_id"],
                        "delivered" if body.simulation_mode else "pending",
                    ),
                )
            conn.execute("update risk_events set status = 'escalating', updated_at = now() where id = %s", (risk_event_id,))
            return _run(conn, row)

    def get_escalation_run(self, escalation_run_id: UUID, patient_id: UUID) -> EscalationRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from escalation_runs where id = %s and patient_id = %s",
                (escalation_run_id, patient_id),
            ).fetchone()
            return _run(conn, row) if row else None

    def acknowledge_escalation_run(
        self,
        escalation_run_id: UUID,
        patient_id: UUID,
        actor_id: UUID | None = None,
        note: str | None = None,
    ) -> EscalationRun | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                update escalation_runs
                set status = 'acknowledged', completed_at = now(), outcome = %s, updated_at = now()
                where id = %s and patient_id = %s
                returning *
                """,
                (note or "acknowledged", escalation_run_id, patient_id),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                insert into escalation_acknowledgements (
                  patient_id, escalation_run_id, acknowledged_by_user_id,
                  acknowledgement_method, response_payload
                )
                values (%s, %s, %s, 'in_app', %s)
                """,
                (patient_id, escalation_run_id, actor_id, _json({"note": note})),
            )
            return _run(conn, row)

    @contextmanager
    def _connect(self):
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError("psycopg_pool is required when DATABASE_URL is set") from exc
        if self._pool is None:
            self._pool = ConnectionPool(
                conninfo=self.database_url,
                kwargs={"row_factory": dict_row},
                min_size=1,
                max_size=5,
                open=False,
            )
            self._pool.open()
        with self._pool.connection() as conn:
            self._apply_database_context(conn)
            yield conn

    def _apply_database_context(self, conn: Any) -> None:
        context = get_database_actor_context()
        if context is None:
            return
        conn.execute(
            "select set_config('app.user_id', %s, true), set_config('app.role', %s, true)",
            (str(context.user_id), context.role),
        )


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _row_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _patient(row: dict[str, Any]) -> PatientProfile:
    payload = _row_dict(row)
    return PatientProfile(
        id=payload["id"],
        account_id=payload["account_id"],
        full_name=payload["full_name"],
        date_of_birth=payload.get("date_of_birth"),
        sex=payload.get("sex"),
        primary_language=payload.get("primary_language") or "en",
        address=payload.get("address") or {},
        emergency_location_notes=payload.get("emergency_location_notes"),
        conditions=payload.get("conditions") or [],
        allergies=payload.get("allergies") or [],
        baseline_notes=payload.get("baseline_notes"),
    )


def _consent(row: dict[str, Any], reason: str | None = None) -> ConsentGrant:
    payload = _row_dict(row)
    return ConsentGrant(
        id=payload["id"],
        patient_id=payload["patient_id"],
        consent_type=payload["consent_type"],
        scope=payload.get("scope") or {},
        channel=payload.get("channel"),
        granted_to_user_id=payload.get("granted_to_user_id"),
        granted_to_contact_id=payload.get("granted_to_contact_id"),
        expires_at=str(payload["expires_at"]) if payload.get("expires_at") else None,
        consent_text_version=payload["consent_text_version"],
        reason=reason,
        status=payload.get("status", "active"),
    )


def _medicine(row: dict[str, Any]) -> Medicine:
    return Medicine(**{key: _json_value(value) for key, value in row.items() if key in Medicine.model_fields})


def _schedule(row: dict[str, Any], medicine: Medicine | None) -> MedicineSchedule:
    payload = _row_dict(row)
    return MedicineSchedule(
        id=payload["id"],
        patient_id=payload["patient_id"],
        medicine_id=payload["medicine_id"],
        medicine=medicine,
        dose=payload["dose"],
        route=payload.get("route"),
        scheduled_times=payload.get("scheduled_times") or [],
        start_date=payload["start_date"],
        end_date=payload.get("end_date"),
        with_food=payload.get("with_food"),
        special_instructions=payload.get("special_instructions"),
        review_status=payload.get("review_status", "pending"),
    )


def _dose_event(row: dict[str, Any]) -> MedicineDoseEvent:
    return MedicineDoseEvent(**{key: _json_value(value) for key, value in row.items() if key in MedicineDoseEvent.model_fields})


def _observation(row: dict[str, Any]) -> Observation:
    return Observation(
        id=row["id"],
        patient_id=row["patient_id"],
        metric_code=row["metric_code"],
        value=_observation_value(row),
        unit=row.get("unit"),
        observed_at=row["observed_at"],
        source_type=row["source_type"],
        reliability_tier=row["reliability_tier"],
        confidence=float(row["confidence"]),
        device_id=row.get("device_id"),
    )


def _observation_value(row: dict[str, Any]) -> int | float | str | bool:
    if row.get("value_numeric") is not None:
        numeric = float(row["value_numeric"])
        return int(numeric) if numeric.is_integer() else numeric
    value_text = row.get("value_text")
    if value_text == "true":
        return True
    if value_text == "false":
        return False
    return value_text or ""


def _document(row: dict[str, Any]) -> MedicalDocument:
    payload = _row_dict(row)
    return MedicalDocument(
        id=payload["id"],
        patient_id=payload["patient_id"],
        original_filename=payload["original_filename"],
        file_type=payload["file_type"],
        document_type=payload.get("document_type"),
        malware_scan_status=payload.get("malware_scan_status", "pending"),
        ocr_status=payload.get("ocr_status", "blocked"),
        extraction_status=payload.get("extraction_status", "blocked"),
        review_status=payload.get("review_status", "pending"),
        created_at=payload.get("created_at") or utcnow(),
    )


def _fact(row: dict[str, Any]) -> ExtractedMedicalFact:
    payload = _row_dict(row)
    return ExtractedMedicalFact(
        id=payload["id"],
        fact_type=payload["fact_type"],
        label=payload["label"],
        value=payload["value"],
        unit=payload.get("unit"),
        effective_date=str(payload["effective_date"]) if payload.get("effective_date") else None,
        confidence=float(payload["confidence"]),
        source_page=payload.get("source_page"),
        source_text_span=payload.get("source_text_span"),
        review_status=payload.get("review_status", "pending"),
        corrected_value=payload.get("corrected_value"),
    )


def _risk_event(row: dict[str, Any], recommended_action: str | None = None) -> RiskEvent:
    payload = _row_dict(row)
    return RiskEvent(
        id=payload["id"],
        patient_id=payload["patient_id"],
        severity=payload["severity"],
        confidence=float(payload["confidence"]),
        reason=payload["reason"],
        evidence=payload.get("evidence_json") or [],
        status=payload.get("status", "open"),
        detected_at=payload.get("detected_at") or utcnow(),
        acknowledged_at=payload.get("acknowledged_at"),
        resolved_at=payload.get("resolved_at"),
        rule_id=payload.get("rule_id"),
        recommended_action=recommended_action,
    )


def _policy(conn: Any, row: dict[str, Any]) -> EscalationPolicy:
    steps = conn.execute(
        "select * from escalation_policy_steps where policy_id = %s order by step_order",
        (row["id"],),
    ).fetchall()
    return EscalationPolicy(
        id=row["id"],
        patient_id=row["patient_id"],
        name=row["name"],
        severity_trigger=row["severity_trigger"],
        patient_confirmation_timeout_seconds=row["patient_confirmation_timeout_seconds"],
        emergency_enabled=row["emergency_enabled"],
        location_sharing_enabled=row["location_sharing_enabled"],
        simulation_mode=row["simulation_mode"],
        active=row["active"],
        steps=[
            {
                "step_order": step["step_order"],
                "action_type": step["action_type"],
                "channel": step["channel"],
                "target_contact_id": step["target_contact_id"],
                "target_role": step["target_role"],
                "template_id": step["template_id"],
                "timeout_seconds": step["timeout_seconds"],
                "retry_count": step["retry_count"],
                "include_location": step["include_location"],
            }
            for step in steps
        ],
    )


def _run(conn: Any, row: dict[str, Any]) -> EscalationRun:
    actions = conn.execute(
        "select * from escalation_actions where escalation_run_id = %s order by step_order, attempt_number",
        (row["id"],),
    ).fetchall()
    return EscalationRun(
        id=row["id"],
        risk_event_id=row["risk_event_id"],
        patient_id=row["patient_id"],
        policy_id=row["policy_id"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
        outcome=row.get("outcome"),
        actions=[
            {
                "id": action["id"],
                "step_order": action["step_order"],
                "attempt_number": action["attempt_number"],
                "action_type": action["action_type"],
                "channel": action["channel"],
                "status": action["status"],
                "target_contact_id": action["target_contact_id"],
                "attempted_at": action["attempted_at"],
                "completed_at": action["completed_at"],
                "provider_message_id": action["provider_message_id"],
                "provider_call_id": action["provider_call_id"],
                "error_code": action["error_code"],
            }
            for action in actions
        ],
    )


def _copy(model: T) -> T:
    if hasattr(model, "model_copy"):
        return model.model_copy(deep=True)
    return model


settings = get_settings()
care_repository: CareRepository = (
    PostgresCareRepository(settings.database_url, settings.document_storage_bucket)
    if settings.use_database
    else InMemoryCareRepository()
)
