from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_tools import (
    AgentToolContractError,
    build_audit_log_payload,
    build_tool_request,
    denied_response,
    authorize_tool_request,
)


PATIENT_ID = "11111111-1111-4111-8111-111111111111"
ACTOR_ID = "22222222-2222-4222-8222-222222222222"


def _payload(**overrides: object) -> dict:
    payload = {
        "patient_id": PATIENT_ID,
        "actor_id": ACTOR_ID,
        "request_id": "req-123",
        "authorization_scope": "agent:tool_call",
        "reason": "patient asked for latest vitals",
        "input": {},
    }
    payload.update(overrides)
    return payload


def test_tool_contract_requires_patient_request_scope_reason_and_input() -> None:
    with pytest.raises(AgentToolContractError, match="patient_id"):
        build_tool_request("get_recent_vitals", _payload(patient_id=""))

    with pytest.raises(AgentToolContractError, match="Unsupported"):
        build_tool_request("unsafe_tool", _payload())


def test_tool_contract_allows_system_actor_when_actor_id_absent() -> None:
    payload = _payload()
    payload.pop("actor_id")

    request = build_tool_request("get_recent_vitals", payload)

    assert request.actor_type == "system"
    assert request.actor_id == "careagent-agent-runtime"


def test_read_tool_requires_agent_tool_call_and_specific_scope() -> None:
    request = build_tool_request("get_recent_vitals", _payload())

    denied = authorize_tool_request(request, granted_scopes={"agent:tool_call"})
    allowed = authorize_tool_request(request, granted_scopes={"agent:tool_call", "observations:read"})

    assert denied.allowed is False
    assert denied.audit_action == "agent.tool_denied"
    assert allowed.allowed is True
    audit = build_audit_log_payload(request, allowed, audit_log_id="audit-1")
    assert audit["phi_access"] is True
    assert audit["request_id"] == "req-123"


def test_critical_voice_call_requires_voice_consent() -> None:
    request = build_tool_request("place_voice_call", _payload(reason="critical event escalation", input={"purpose": "emergency"}))

    denied = authorize_tool_request(
        request,
        granted_scopes={"agent:tool_call", "escalation:write"},
        consents={"voice_calls": False},
        emergency_enabled=True,
    )

    assert denied.allowed is False
    assert "Voice-call consent" in denied.reason
    response = denied_response(denied, audit_log_id="audit-1").as_dict()
    assert response["status"] == "denied"
    assert response["error_code"] == "policy_denied"


def test_critical_escalation_requires_emergency_policy_and_consent() -> None:
    request = build_tool_request(
        "start_escalation_protocol",
        _payload(reason="critical SpO2 policy escalation", input={"severity": "critical"}),
    )

    no_policy = authorize_tool_request(
        request,
        granted_scopes={"agent:tool_call", "escalation:write"},
        consents={"emergency_escalation": True},
        emergency_enabled=False,
    )
    allowed = authorize_tool_request(
        request,
        granted_scopes={"agent:tool_call", "escalation:write"},
        consents={"emergency_escalation": True},
        emergency_enabled=True,
        simulation_mode=True,
    )

    assert no_policy.allowed is False
    assert allowed.allowed is True
    assert allowed.metadata["simulation_mode"] is True


def test_location_is_denied_unless_consent_and_policy_allow_it() -> None:
    request = build_tool_request(
        "start_escalation_protocol",
        _payload(reason="fall escalation", input={"severity": "critical", "include_location": True}),
    )

    denied = authorize_tool_request(
        request,
        granted_scopes={"agent:tool_call", "escalation:write"},
        consents={"emergency_escalation": True, "location_sharing": False},
        emergency_enabled=True,
        location_sharing_enabled=True,
    )
    allowed = authorize_tool_request(
        request,
        granted_scopes={"agent:tool_call", "escalation:write"},
        consents={"emergency_escalation": True, "location_sharing": True},
        emergency_enabled=True,
        location_sharing_enabled=True,
    )

    assert denied.allowed is False
    assert "Location-sharing consent" in denied.reason
    assert allowed.allowed is True
