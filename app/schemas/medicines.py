from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.schemas.common import ContactChannel, ScheduledTime, utcnow


class MedicineCreateRequest(BaseModel):
    name: str
    normalized_name: str | None = None
    strength: str | None = None
    form: str | None = None
    instructions: str | None = None
    source_document_id: UUID | None = None


class Medicine(MedicineCreateRequest):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    active: bool = True


class MedicineScheduleUpsertRequest(BaseModel):
    medicine_id: UUID
    dose: str
    route: str | None = None
    scheduled_times: list[ScheduledTime]
    start_date: date
    end_date: date | None = None
    with_food: str | None = None
    special_instructions: str | None = None
    review_status: Literal["pending", "approved"] = "pending"


class MedicineSchedule(MedicineScheduleUpsertRequest):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    medicine: Medicine | None = None


class DoseEventCreateRequest(BaseModel):
    schedule_id: UUID
    scheduled_at: datetime
    status: Literal["taken", "skipped", "missed", "snoozed"]
    source_channel: ContactChannel | None = None
    notes: str | None = None
    idempotency_key: str | None = None


class MedicineDoseEvent(DoseEventCreateRequest):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    recorded_at: datetime = Field(default_factory=utcnow)
