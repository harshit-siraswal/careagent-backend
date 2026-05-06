from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence


class PolicyDecisionStatus(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


class CriticalAction(StrEnum):
    CREATE_ALERT = "create_alert"
    SEND_CHANNEL_MESSAGE = "send_channel_message"
    PLACE_VOICE_CALL = "place_voice_call"
    START_ESCALATION_PROTOCOL = "start_escalation_protocol"
    SHARE_LOCATION = "share_location"
    BOOK_APPOINTMENT_REQUEST = "book_appointment_request"


@dataclass(frozen=True)
class PolicyContext:
    patient_id: str
    actor_id: str
    request_id: str
    authorization_scope: str
    reason: str
    actor_type: str = "agent"
    scopes: frozenset[str] = field(default_factory=frozenset)
    consents: Mapping[str, bool] = field(default_factory=dict)
    emergency_enabled: bool = False
    location_sharing_enabled: bool = False
    simulation_mode: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    status: PolicyDecisionStatus
    action: str
    reason: str
    required_scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...] = ()
    audit_action: str = "agent.tool_called"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.status == PolicyDecisionStatus.ALLOW

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action,
            "reason": self.reason,
            "required_scopes": list(self.required_scopes),
            "missing_scopes": list(self.missing_scopes),
            "audit_action": self.audit_action,
            "metadata": dict(self.metadata),
        }


TOOL_REQUIRED_SCOPES: dict[str, tuple[str, ...]] = {
    "get_patient_profile": ("patient:read",),
    "get_recent_vitals": ("observations:read",),
    "get_device_status": ("devices:read",),
    "get_medicine_schedule": ("medicines:read",),
    "log_medicine_taken": ("medicines:write",),
    "search_medical_documents": ("documents:read",),
    "create_alert": ("alerts:write",),
    "request_patient_confirmation": ("agent:write",),
    "send_channel_message": ("agent:write",),
    "place_voice_call": ("escalation:write",),
    "start_escalation_protocol": ("escalation:write",),
    "book_appointment_request": ("agent:write",),
}

PHI_READING_TOOLS = {
    "get_patient_profile",
    "get_recent_vitals",
    "get_device_status",
    "get_medicine_schedule",
    "search_medical_documents",
}

CRITICAL_TOOLS = {
    "create_alert",
    "send_channel_message",
    "place_voice_call",
    "start_escalation_protocol",
}


def evaluate_tool_policy(tool_name: str, context: PolicyContext, tool_input: Mapping[str, Any] | None = None) -> PolicyDecision:
    required = ("agent:tool_call",) + TOOL_REQUIRED_SCOPES.get(tool_name, ())
    missing = tuple(scope for scope in required if scope not in context.scopes and "patient:*" not in context.scopes)
    if missing:
        return PolicyDecision(
            status=PolicyDecisionStatus.DENY,
            action=tool_name,
            reason="Missing required authorization scope.",
            required_scopes=required,
            missing_scopes=missing,
            audit_action="agent.tool_denied",
        )

    if not context.reason.strip():
        return PolicyDecision(
            status=PolicyDecisionStatus.DENY,
            action=tool_name,
            reason="Reason is required for agent tool calls.",
            required_scopes=required,
            audit_action="agent.tool_denied",
        )

    action_decision = evaluate_critical_action(tool_name, context, tool_input or {})
    if action_decision is not None:
        return action_decision

    return PolicyDecision(
        status=PolicyDecisionStatus.ALLOW,
        action=tool_name,
        reason="Allowed by deterministic tool policy.",
        required_scopes=required,
        metadata={"phi_access": tool_name in PHI_READING_TOOLS},
    )


def evaluate_critical_action(
    action: str,
    context: PolicyContext,
    payload: Mapping[str, Any] | None = None,
) -> PolicyDecision | None:
    if action not in CRITICAL_TOOLS:
        return None

    required = ("agent:tool_call",) + TOOL_REQUIRED_SCOPES.get(action, ())
    metadata = {"phi_access": True, "simulation_mode": context.simulation_mode}
    payload = payload or {}

    if action == CriticalAction.PLACE_VOICE_CALL:
        if not context.consents.get("voice_calls", False):
            return _deny(action, required, "Voice-call consent is not active.", metadata)
        if not context.emergency_enabled and payload.get("purpose") == "emergency":
            return _deny(action, required, "Emergency voice action is disabled by policy.", metadata)

    if action == CriticalAction.START_ESCALATION_PROTOCOL:
        severity = str(payload.get("severity", "")).lower()
        if severity == "critical":
            if not context.emergency_enabled:
                return _deny(action, required, "Critical escalation requires an active emergency policy.", metadata)
            if not context.consents.get("emergency_escalation", False):
                return _deny(action, required, "Emergency escalation consent is not active.", metadata)
        if payload.get("include_location"):
            location_decision = evaluate_location_gate(action, context, required)
            if not location_decision.allowed:
                return location_decision

    if action == CriticalAction.SEND_CHANNEL_MESSAGE:
        channel = str(payload.get("channel", ""))
        if channel and not context.consents.get(f"channel:{channel}", True):
            return _deny(action, required, f"Consent for {channel} messages is not active.", metadata)

    return PolicyDecision(
        status=PolicyDecisionStatus.ALLOW,
        action=action,
        reason="Critical action allowed by deterministic policy gates.",
        required_scopes=required,
        metadata=metadata,
    )


def evaluate_location_gate(action: str, context: PolicyContext, required_scopes: Sequence[str]) -> PolicyDecision:
    if not context.location_sharing_enabled:
        return _deny(action, tuple(required_scopes), "Location sharing is disabled by policy.", {"phi_access": True})
    if not context.consents.get("location_sharing", False):
        return _deny(action, tuple(required_scopes), "Location-sharing consent is not active.", {"phi_access": True})
    return PolicyDecision(
        status=PolicyDecisionStatus.ALLOW,
        action=action,
        reason="Location sharing allowed by consent and policy.",
        required_scopes=tuple(required_scopes),
        metadata={"phi_access": True},
    )


def _deny(action: str, required: tuple[str, ...], reason: str, metadata: Mapping[str, Any]) -> PolicyDecision:
    return PolicyDecision(
        status=PolicyDecisionStatus.DENY,
        action=action,
        reason=reason,
        required_scopes=required,
        audit_action="agent.tool_denied",
        metadata=metadata,
    )
