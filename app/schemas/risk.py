from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.schemas.common import ContactChannel, RiskSeverity, utcnow


class RiskEventCreateRequest(BaseModel):
    severity: RiskSeverity
    confidence: float
    reason: str
    evidence: list[dict[str, Any]]
    rule_id: UUID | None = None
    recommended_action: str | None = None


class RiskEvent(RiskEventCreateRequest):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    status: Literal["open", "acknowledged", "escalating", "resolved", "false_positive", "cancelled"] = "open"
    detected_at: datetime = Field(default_factory=utcnow)
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None


class Alert(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    risk_event_id: UUID | None = None
    severity: RiskSeverity = "informational"
    title: str
    body: str
    status: Literal["open", "acknowledged", "resolved", "suppressed", "expired"] = "open"
    created_at: datetime = Field(default_factory=utcnow)


class AcknowledgeRequest(BaseModel):
    note: str | None = None
    classification: Literal["true_positive", "false_positive", "unknown"] | None = None


class EscalationPolicyStep(BaseModel):
    step_order: int
    action_type: Literal[
        "patient_prompt",
        "send_message",
        "place_call",
        "share_location",
        "wait_for_ack",
        "create_incident_summary",
    ]
    channel: ContactChannel
    target_contact_id: UUID | None = None
    target_role: Literal["family", "caretaker", "nurse", "doctor", "ambulance", "hospital", "other"] | None = None
    template_id: str | None = None
    timeout_seconds: int | None = None
    retry_count: int | None = None
    include_location: bool | None = None


class EscalationPolicyCreateRequest(BaseModel):
    name: str
    severity_trigger: RiskSeverity
    patient_confirmation_timeout_seconds: int = 120
    emergency_enabled: bool = False
    location_sharing_enabled: bool = False
    simulation_mode: bool = True
    steps: list[EscalationPolicyStep]


class EscalationPolicy(EscalationPolicyCreateRequest):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    active: bool = True


class EscalationStartRequest(BaseModel):
    policy_id: UUID
    requested_by: Literal["policy_engine", "patient", "caretaker", "doctor", "nurse", "admin", "agent"]
    simulation_mode: bool = True
    reason: str | None = None


class EscalationAction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    step_order: int
    attempt_number: int = 1
    action_type: str
    channel: ContactChannel
    status: Literal[
        "pending",
        "attempting",
        "sent",
        "delivered",
        "answered",
        "acknowledged",
        "failed",
        "skipped",
        "cancelled",
    ] = "pending"
    target_contact_id: UUID | None = None
    attempted_at: datetime | None = None
    completed_at: datetime | None = None
    provider_message_id: str | None = None
    provider_call_id: str | None = None
    error_code: str | None = None


class EscalationRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    risk_event_id: UUID
    patient_id: UUID
    policy_id: UUID
    status: Literal["pending", "running", "awaiting_ack", "acknowledged", "completed", "failed", "cancelled"] = "pending"
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    outcome: str | None = None
    actions: list[EscalationAction] = Field(default_factory=list)
