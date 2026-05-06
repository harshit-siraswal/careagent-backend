from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


ContactChannel = Literal["push", "in_app", "whatsapp", "telegram", "sms", "voice", "email"]
ProcessingStatus = Literal["queued", "running", "blocked", "completed", "failed", "cancelled"]
RiskSeverity = Literal["informational", "low", "moderate", "high", "critical"]
SourceType = Literal["healthkit", "health_connect", "ble", "vendor_api", "fhir", "ocr", "manual", "simulator"]
ReliabilityTier = Literal["clinical", "os_aggregator", "standard_ble", "vendor_api", "manual_or_ocr", "unknown"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class ItemsResponse(BaseModel):
    items: list[Any] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "careagent-backend-api"
    version: str = "0.1.0"


class AuthSessionRequest(BaseModel):
    provider: str = "internal_test"
    provider_token: str


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    user_id: UUID = Field(default_factory=uuid4)
    role: str = "patient"
    mfa: bool = False


class MeResponse(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    role: str
    mfa: bool = False
    grants: list[dict[str, Any]] = Field(default_factory=list)


class DeviceCatalogEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    brand: str
    model: str
    category: str
    support_tier: str = "stub"
    connection_methods: list[str] = Field(default_factory=list)
    supported_metrics: list[str] = Field(default_factory=list)
    validation_status: str = "unvalidated"
    notes: str | None = None


class DeviceCreateRequest(BaseModel):
    display_name: str
    brand: str | None = None
    model: str | None = None
    category: str
    connection_method: str
    supported_metrics: list[str] = Field(default_factory=list)
    reliability_tier: ReliabilityTier = "unknown"


class Device(DeviceCreateRequest):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    active: bool = True
    connection_state: dict[str, Any] = Field(default_factory=lambda: {"status": "stub"})


class ObservationCreate(BaseModel):
    metric_code: str
    value: int | float | str | bool
    unit: str | None = None
    observed_at: datetime = Field(default_factory=utcnow)
    source_type: SourceType = "manual"
    reliability_tier: ReliabilityTier = "unknown"
    confidence: float = 1.0
    device_id: UUID | None = None


class ObservationBatchCreateRequest(BaseModel):
    observations: list[ObservationCreate]
    idempotency_key: str | None = None


class Observation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    metric_code: str
    value: int | float | str | bool
    unit: str | None = None
    observed_at: datetime
    source_type: SourceType
    reliability_tier: ReliabilityTier
    confidence: float
    device_id: UUID | None = None


class ObservationListResponse(BaseModel):
    items: list[Observation] = Field(default_factory=list)
    next_cursor: str | None = None


class ObservationBatchCreateResponse(BaseModel):
    accepted_count: int
    batch_id: UUID = Field(default_factory=uuid4)
    status: str = "accepted"


class VitalReading(BaseModel):
    metric_code: str
    value: int | float | str | bool
    unit: str
    observed_at: datetime = Field(default_factory=utcnow)
    source: str = "stub"
    freshness: Literal["fresh", "stale", "old", "unknown"] = "unknown"


class LatestVitalsResponse(BaseModel):
    patient_id: UUID
    readings: list[VitalReading] = Field(default_factory=list)


class ScheduledTime(BaseModel):
    local_time: str
    days_of_week: list[int] | None = None


class DateRange(BaseModel):
    start_date: date
    end_date: date | None = None
