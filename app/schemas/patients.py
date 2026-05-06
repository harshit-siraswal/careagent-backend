from datetime import date
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.schemas.common import ContactChannel


class PatientCreateRequest(BaseModel):
    full_name: str
    date_of_birth: date | None = None
    sex: str | None = None
    primary_language: str = "en"
    address: dict[str, Any] = Field(default_factory=dict)
    emergency_location_notes: str | None = None
    conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    baseline_notes: str | None = None


class PatientUpdateRequest(BaseModel):
    full_name: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    primary_language: str | None = None
    address: dict[str, Any] | None = None
    emergency_location_notes: str | None = None
    conditions: list[str] | None = None
    allergies: list[str] | None = None
    baseline_notes: str | None = None


class PatientProfile(PatientCreateRequest):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID = Field(default_factory=uuid4)


class PatientSummary(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    full_name: str
    primary_language: str = "en"


class CareTeamMemberCreateRequest(BaseModel):
    display_name: str
    role: str
    priority_order: int = 100
    permissions: list[str] = Field(default_factory=list)
    channel: ContactChannel | None = None
    contact: dict[str, Any] = Field(default_factory=dict)


class CareTeamMember(CareTeamMemberCreateRequest):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    active: bool = True


class ConsentGrantRequest(BaseModel):
    consent_type: str
    scope: dict[str, Any] = Field(default_factory=dict)
    channel: ContactChannel | None = None
    granted_to_user_id: UUID | None = None
    granted_to_contact_id: UUID | None = None
    expires_at: str | None = None
    consent_text_version: str
    reason: str | None = None


class RevokeConsentRequest(BaseModel):
    reason: str | None = None


class ConsentGrant(ConsentGrantRequest):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    status: str = "active"
