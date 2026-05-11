from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.care_data import care_repository


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_care_repository() -> None:
    care_repository.reset()
    yield
    care_repository.reset()


def auth_headers(patient_id: str, permissions: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer test-token",
        "X-CareAgent-Role": "caretaker",
        "X-CareAgent-Patient-Id": patient_id,
        "X-CareAgent-Permissions": permissions,
        "X-Request-Id": "pilot-test",
    }


def test_pilot_risk_escalation_acknowledgement_and_audit_flow() -> None:
    patient_id = str(uuid4())
    permissions = ",".join(
        [
            "risk:write",
            "alerts:read",
            "alerts:write",
            "escalation:read",
            "escalation:write",
            "audit:read",
        ]
    )
    headers = auth_headers(patient_id, permissions)

    risk_response = client.post(
        f"/patients/{patient_id}/risk-events",
        headers=headers,
        json={
            "severity": "moderate",
            "confidence": 0.9,
            "reason": "Pilot manual vital requires review.",
            "evidence": [{"source": "pilot"}],
            "recommended_action": "create_alert",
        },
    )
    assert risk_response.status_code == 201
    risk_event_id = risk_response.json()["id"]

    alerts_response = client.get(f"/patients/{patient_id}/alerts", headers=headers)
    assert alerts_response.status_code == 200
    assert alerts_response.json()["items"][0]["risk_event_id"] == risk_event_id

    policy_response = client.post(
        f"/patients/{patient_id}/escalation-policies",
        headers=headers,
        json={
            "name": "Pilot simulation",
            "severity_trigger": "moderate",
            "simulation_mode": True,
            "steps": [
                {
                    "step_order": 1,
                    "action_type": "send_message",
                    "channel": "in_app",
                    "target_role": "family",
                }
            ],
        },
    )
    assert policy_response.status_code == 201

    escalation_response = client.post(
        f"/risk-events/{risk_event_id}/escalate",
        headers={**headers, "Idempotency-Key": "pilot-escalation-1"},
        json={
            "policy_id": policy_response.json()["id"],
            "requested_by": "patient",
            "simulation_mode": True,
            "reason": "pilot",
        },
    )
    assert escalation_response.status_code == 201
    escalation = escalation_response.json()
    assert escalation["status"] == "awaiting_ack"
    assert escalation["actions"][0]["status"] == "delivered"

    ack_response = client.post(
        f"/escalation-runs/{escalation['id']}/acknowledge",
        headers=headers,
        json={"note": "Handled by caretaker."},
    )
    assert ack_response.status_code == 200
    assert ack_response.json()["status"] == "acknowledged"

    audit_response = client.get(f"/patients/{patient_id}/audit-logs", headers=headers)
    assert audit_response.status_code == 200
    actions = {item["action"] for item in audit_response.json()["items"]}
    assert "risk_event.created" in actions
    assert "escalation.started" in actions
