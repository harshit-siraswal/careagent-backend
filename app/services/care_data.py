from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Protocol, TypeVar
from uuid import UUID, uuid4

from app.schemas import (
    ConsentGrant,
    ConsentGrantRequest,
    DoseEventCreateRequest,
    LatestVitalsResponse,
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
)
from app.schemas.common import VitalReading


T = TypeVar("T")


class CareRepository(Protocol):
    def reset(self) -> None: ...

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


class InMemoryCareRepository:
    """Process-local repository for tests and early client integration."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._patients: dict[UUID, PatientProfile] = {}
            self._consents: dict[UUID, ConsentGrant] = {}
            self._medicines: dict[UUID, Medicine] = {}
            self._medicine_schedules: dict[UUID, MedicineSchedule] = {}
            self._dose_events: dict[UUID, MedicineDoseEvent] = {}
            self._observations: dict[UUID, Observation] = {}

    def create_patient(self, body: PatientCreateRequest, account_id: UUID) -> PatientProfile:
        patient = PatientProfile(**body.model_dump(), account_id=account_id)
        with self._lock:
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


def _copy(model: T) -> T:
    if hasattr(model, "model_copy"):
        return model.model_copy(deep=True)
    return model


care_repository: CareRepository = InMemoryCareRepository()
