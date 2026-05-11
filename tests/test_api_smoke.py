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


def auth_headers(patient_id: str, permissions: str = "patient:read") -> dict[str, str]:
    return {
        "Authorization": "Bearer test-token",
        "X-CareAgent-Role": "caretaker",
        "X-CareAgent-Patient-Id": patient_id,
        "X-CareAgent-Permissions": permissions,
        "X-Request-Id": "test-request",
    }


def patient_headers(actor_id: str, patient_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer test-token",
        "X-CareAgent-Actor-Id": actor_id,
        "X-CareAgent-Role": "patient",
        "X-Request-Id": "patient-bootstrap-test",
    }
    if patient_id is not None:
        headers["X-CareAgent-Patient-Id"] = patient_id
    return headers


def test_health_is_public() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_authenticated_routes_require_bearer_token() -> None:
    response = client.get("/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_patient_scope_allows_matching_patient_and_permission() -> None:
    create_response = client.post(
        "/patients",
        headers=auth_headers(str(uuid4()), permissions="patient:write"),
        json={"full_name": "Scope Test Patient"},
    )
    assert create_response.status_code == 201

    patient_id = create_response.json()["id"]
    response = client.get(f"/patients/{patient_id}", headers=auth_headers(patient_id))

    assert response.status_code == 200
    assert response.json()["id"] == patient_id


def test_patient_can_bootstrap_exactly_one_self_owned_profile() -> None:
    actor_id = str(uuid4())
    response = client.post(
        "/patients",
        headers=patient_headers(actor_id),
        json={"full_name": "First Patient"},
    )
    assert response.status_code == 201

    duplicate = client.post(
        "/patients",
        headers=patient_headers(actor_id),
        json={"full_name": "Duplicate Patient"},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "patient_profile_already_exists"


def test_patient_scope_denies_cross_patient_access_without_grant() -> None:
    actor_a = str(uuid4())
    actor_b = str(uuid4())
    patient_a = client.post(
        "/patients",
        headers=patient_headers(actor_a),
        json={"full_name": "Patient A"},
    ).json()["id"]
    patient_b = client.post(
        "/patients",
        headers=patient_headers(actor_b),
        json={"full_name": "Patient B"},
    ).json()["id"]

    response = client.get(
        f"/patients/{patient_b}",
        headers=patient_headers(actor_a, patient_id=patient_a),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "patient_scope_denied"


def test_patient_scope_denies_missing_permission() -> None:
    patient_id = str(uuid4())
    response = client.post(
        f"/patients/{patient_id}/devices",
        headers=auth_headers(patient_id, permissions="devices:read"),
        json={
            "display_name": "Manual pulse oximeter",
            "category": "pulse_oximeter",
            "connection_method": "manual",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "patient_scope_denied"


def test_document_upload_requires_idempotency_key_and_returns_blocked_processing() -> None:
    patient_id = str(uuid4())
    headers = auth_headers(patient_id, permissions="documents:write")
    response = client.post(
        f"/patients/{patient_id}/documents",
        headers={**headers, "Idempotency-Key": "doc-upload-1"},
        json={
            "original_filename": "labs.pdf",
            "file_type": "application/pdf",
            "file_size_bytes": 1024,
            "sha256": "abc123",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["document"]["patient_id"] == patient_id
    assert payload["document"]["malware_scan_status"] == "pending"
    assert payload["document"]["ocr_status"] == "blocked"
    assert payload["upload"]["method"] == "PUT"


def test_agent_message_returns_stubbed_response_with_audit_id() -> None:
    patient_id = str(uuid4())
    response = client.post(
        "/agent/messages",
        headers=auth_headers(patient_id, permissions="agent:write"),
        json={"patient_id": patient_id, "channel": "in_app", "message": "What should I do next?"},
    )

    assert response.status_code == 200
    assert response.json()["response"].startswith("Stub agent response")
    assert response.json()["audit_log_id"]
