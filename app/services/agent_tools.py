from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.services.policy import PHI_READING_TOOLS, PolicyContext, PolicyDecision, evaluate_tool_policy


AGENT_TOOL_NAMES = frozenset(
    {
        "get_patient_profile",
        "get_recent_vitals",
        "get_device_status",
        "get_medicine_schedule",
        "log_medicine_taken",
        "search_medical_documents",
        "create_alert",
        "request_patient_confirmation",
        "send_channel_message",
        "place_voice_call",
        "start_escalation_protocol",
        "book_appointment_request",
    }
)


class AgentToolContractError(ValueError):
    pass


@dataclass(frozen=True)
class AgentToolRequest:
    tool_name: str
    patient_id: str
    actor_id: str
    request_id: str
    authorization_scope: str
    reason: str
    input: Mapping[str, Any] = field(default_factory=dict)
    actor_type: str = "agent"

    def as_record(self, decision: PolicyDecision) -> dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "tool_name": self.tool_name,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "request_id": self.request_id,
            "authorization_scope": self.authorization_scope,
            "reason": self.reason,
            "input_json": dict(self.input),
            "policy_decision": decision.as_dict(),
            "status": "authorized" if decision.allowed else "denied",
        }


@dataclass(frozen=True)
class AgentToolResponse:
    status: str
    result: Mapping[str, Any]
    audit_log_id: str | None
    safe_user_message: str | None = None
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "result": dict(self.result),
            "audit_log_id": self.audit_log_id,
        }
        if self.safe_user_message:
            payload["safe_user_message"] = self.safe_user_message
        if self.error_code:
            payload["error_code"] = self.error_code
        return payload


def build_tool_request(tool_name: str, payload: Mapping[str, Any], *, system_actor_id: str = "careagent-agent-runtime") -> AgentToolRequest:
    if tool_name not in AGENT_TOOL_NAMES:
        raise AgentToolContractError(f"Unsupported agent tool: {tool_name}")

    missing = []
    for field_name in ("patient_id", "request_id", "authorization_scope", "reason", "input"):
        if field_name not in payload or payload[field_name] in (None, ""):
            missing.append(field_name)
    if missing:
        raise AgentToolContractError(f"Missing required tool contract fields: {', '.join(missing)}")

    actor_id = str(payload.get("actor_id") or system_actor_id)
    actor_type = "system" if "actor_id" not in payload or payload.get("actor_id") in (None, "") else "agent"
    _validate_uuid_like("patient_id", str(payload["patient_id"]))
    if actor_type != "system":
        _validate_uuid_like("actor_id", actor_id)

    return AgentToolRequest(
        tool_name=tool_name,
        patient_id=str(payload["patient_id"]),
        actor_id=actor_id,
        request_id=str(payload["request_id"]),
        authorization_scope=str(payload["authorization_scope"]),
        reason=str(payload["reason"]),
        input=dict(payload["input"]),
        actor_type=actor_type,
    )


def authorize_tool_request(
    request: AgentToolRequest,
    *,
    granted_scopes: set[str] | frozenset[str],
    consents: Mapping[str, bool] | None = None,
    emergency_enabled: bool = False,
    location_sharing_enabled: bool = False,
    simulation_mode: bool = True,
) -> PolicyDecision:
    context = PolicyContext(
        patient_id=request.patient_id,
        actor_id=request.actor_id,
        request_id=request.request_id,
        authorization_scope=request.authorization_scope,
        reason=request.reason,
        actor_type=request.actor_type,
        scopes=frozenset(granted_scopes),
        consents=consents or {},
        emergency_enabled=emergency_enabled,
        location_sharing_enabled=location_sharing_enabled,
        simulation_mode=simulation_mode,
    )
    return evaluate_tool_policy(request.tool_name, context, request.input)


def build_audit_log_payload(request: AgentToolRequest, decision: PolicyDecision, *, audit_log_id: str | None = None) -> dict[str, Any]:
    return {
        "id": audit_log_id,
        "actor_type": request.actor_type,
        "actor_id": request.actor_id,
        "patient_id": request.patient_id,
        "action": decision.audit_action,
        "resource_type": "agent_tool_call",
        "resource_id": request.request_id,
        "outcome": "success" if decision.allowed else "denied",
        "phi_access": request.tool_name in PHI_READING_TOOLS or bool(decision.metadata.get("phi_access")),
        "reason": request.reason,
        "request_id": request.request_id,
        "metadata_json": {
            "tool_name": request.tool_name,
            "authorization_scope": request.authorization_scope,
            "policy_decision": decision.as_dict(),
        },
    }


def denied_response(decision: PolicyDecision, audit_log_id: str | None) -> AgentToolResponse:
    return AgentToolResponse(
        status="denied",
        result={"policy_decision": decision.as_dict()},
        audit_log_id=audit_log_id,
        safe_user_message="I cannot perform that action because backend policy did not approve it.",
        error_code="policy_denied",
    )


def ok_response(result: Mapping[str, Any], audit_log_id: str | None) -> AgentToolResponse:
    return AgentToolResponse(status="ok", result=dict(result), audit_log_id=audit_log_id)


def _validate_uuid_like(field_name: str, value: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise AgentToolContractError(f"{field_name} must be a UUID") from exc
