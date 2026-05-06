from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain.channels import Channel, DispatchAttempt


class RiskSeverity(StrEnum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_ACK = "awaiting_ack"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EscalationActionStatus(StrEnum):
    PENDING = "pending"
    ATTEMPTING = "attempting"
    SENT = "sent"
    DELIVERED = "delivered"
    ANSWERED = "answered"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class SimulationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RiskEvent:
    id: str
    patient_id: str
    severity: RiskSeverity
    reason: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ConsentState:
    voice_calls: bool = True
    emergency_services: bool = False
    location_sharing: bool = False
    channels: dict[Channel, bool] = field(default_factory=dict)

    def allows_channel(self, channel: Channel) -> bool:
        if channel == Channel.VOICE and not self.voice_calls:
            return False
        return self.channels.get(channel, True)


@dataclass(frozen=True)
class EscalationPolicyStep:
    step_order: int
    action_type: str
    channel: Channel
    target_contact_id: str | None = None
    target_role: str | None = None
    template_id: str | None = None
    script_id: str | None = None
    timeout_seconds: int = 60
    retry_count: int = 0
    retry_delay_seconds: int = 30
    include_location: bool = False
    public_emergency_number: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class EscalationPolicy:
    id: str
    patient_id: str
    name: str
    severity_trigger: RiskSeverity
    steps: tuple[EscalationPolicyStep, ...]
    emergency_enabled: bool = False
    simulation_mode: bool = True
    active: bool = True


@dataclass
class EscalationAction:
    id: str
    step_order: int
    action_type: str
    channel: Channel
    status: EscalationActionStatus = EscalationActionStatus.PENDING
    target_contact_id: str | None = None
    template_id: str | None = None
    script_id: str | None = None
    dispatch_attempts: list[DispatchAttempt] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Acknowledgement:
    id: str
    escalation_run_id: str
    acknowledgement_method: str
    channel: Channel | None = None
    escalation_action_id: str | None = None
    acknowledged_by_contact_id: str | None = None
    acknowledged_by_user_id: str | None = None
    response_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class EscalationRun:
    id: str
    patient_id: str
    risk_event_id: str
    policy_id: str
    idempotency_key: str
    requested_by: str
    status: EscalationRunStatus = EscalationRunStatus.PENDING
    outcome: str | None = None
    actions: list[EscalationAction] = field(default_factory=list)
    acknowledgements: list[Acknowledgement] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmergencySimulation:
    id: str
    patient_id: str
    scenario_key: str
    status: SimulationStatus
    expected_steps: list[dict[str, Any]]
    actual_summary: dict[str, Any] = field(default_factory=dict)
    blocked_reasons: list[str] = field(default_factory=list)
    escalation_run: EscalationRun | None = None

