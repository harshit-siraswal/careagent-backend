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
        "X-Request-Id": "care-data-test",
    }


def test_patient_create_list_get_and_update_use_in_memory_repository() -> None:
    response = client.post(
        "/patients",
        headers=auth_headers(str(uuid4()), "patient:write"),
        json={
            "full_name": "Asha Rao",
            "date_of_birth": "1955-02-14",
            "primary_language": "hi",
            "conditions": ["diabetes"],
        },
    )

    assert response.status_code == 201
    patient = response.json()
    patient_id = patient["id"]
    assert patient["full_name"] == "Asha Rao"

    list_response = client.get(f"/patients", headers=auth_headers(patient_id, "patient:read"))
    get_response = client.get(f"/patients/{patient_id}", headers=auth_headers(patient_id, "patient:read"))
    update_response = client.patch(
        f"/patients/{patient_id}",
        headers=auth_headers(patient_id, "patient:write"),
        json={"full_name": "Asha Mehta", "allergies": ["penicillin"]},
    )

    assert list_response.status_code == 200
    assert list_response.json()["items"] == [{"id": patient_id, "full_name": "Asha Rao", "primary_language": "hi"}]
    assert get_response.status_code == 200
    assert get_response.json()["conditions"] == ["diabetes"]
    assert update_response.status_code == 200
    assert update_response.json()["full_name"] == "Asha Mehta"
    assert update_response.json()["allergies"] == ["penicillin"]


def test_consent_create_list_get_and_revoke_use_in_memory_repository() -> None:
    patient_id = str(uuid4())
    response = client.post(
        f"/patients/{patient_id}/consents",
        headers=auth_headers(patient_id, "consent:write"),
        json={
            "consent_type": "medicine_reminders",
            "scope": {"channels": ["sms"]},
            "channel": "sms",
            "consent_text_version": "v1",
            "reason": "patient onboarding",
        },
    )

    assert response.status_code == 201
    consent = response.json()
    consent_id = consent["id"]

    list_response = client.get(f"/patients/{patient_id}/consents", headers=auth_headers(patient_id, "consent:read"))
    get_response = client.get(f"/patients/{patient_id}/consents/{consent_id}", headers=auth_headers(patient_id, "consent:read"))
    revoke_response = client.post(
        f"/patients/{patient_id}/consents/{consent_id}/revoke",
        headers=auth_headers(patient_id, "consent:write"),
        json={"reason": "patient withdrew"},
    )

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["consent_type"] == "medicine_reminders"
    assert get_response.status_code == 200
    assert get_response.json()["scope"] == {"channels": ["sms"]}
    assert revoke_response.status_code == 200
    assert revoke_response.json()["status"] == "revoked"
    assert revoke_response.json()["consent_text_version"] == "v1"


def test_medicine_create_list_get_schedule_and_dose_use_in_memory_repository() -> None:
    patient_id = str(uuid4())
    medicine_response = client.post(
        f"/patients/{patient_id}/medicines",
        headers=auth_headers(patient_id, "medicines:write"),
        json={"name": "Metformin", "strength": "500 mg", "instructions": "Take after meals"},
    )

    assert medicine_response.status_code == 201
    medicine = medicine_response.json()
    medicine_id = medicine["id"]

    list_response = client.get(f"/patients/{patient_id}/medicines", headers=auth_headers(patient_id, "medicines:read"))
    get_response = client.get(f"/patients/{patient_id}/medicines/{medicine_id}", headers=auth_headers(patient_id, "medicines:read"))
    schedule_response = client.post(
        f"/patients/{patient_id}/medicine-schedule",
        headers=auth_headers(patient_id, "medicines:write"),
        json={
            "medicine_id": medicine_id,
            "dose": "1 tablet",
            "scheduled_times": [{"local_time": "08:00"}],
            "start_date": "2026-05-08",
            "review_status": "approved",
        },
    )
    schedule_list_response = client.get(
        f"/patients/{patient_id}/medicine-schedule",
        headers=auth_headers(patient_id, "medicines:read"),
    )
    dose_response = client.post(
        f"/patients/{patient_id}/dose-events",
        headers=auth_headers(patient_id, "medicines:write"),
        json={
            "schedule_id": schedule_response.json()["id"],
            "scheduled_at": "2026-05-08T08:00:00+00:00",
            "status": "taken",
            "source_channel": "in_app",
        },
    )

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == medicine_id
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Metformin"
    assert schedule_response.status_code == 200
    assert schedule_response.json()["medicine"]["id"] == medicine_id
    assert schedule_list_response.status_code == 200
    assert schedule_list_response.json()["items"][0]["medicine_id"] == medicine_id
    assert dose_response.status_code == 201
    assert dose_response.json()["patient_id"] == patient_id


def test_observation_create_list_get_and_latest_vitals_use_in_memory_repository() -> None:
    patient_id = str(uuid4())
    response = client.post(
        f"/patients/{patient_id}/observations",
        headers=auth_headers(patient_id, "observations:write"),
        json={
            "observations": [
                {
                    "metric_code": "heart_rate",
                    "value": 92,
                    "unit": "bpm",
                    "observed_at": "2026-05-08T08:00:00+00:00",
                    "source_type": "manual",
                    "reliability_tier": "manual_or_ocr",
                },
                {
                    "metric_code": "spo2",
                    "value": 97,
                    "unit": "%",
                    "observed_at": "2026-05-08T08:01:00+00:00",
                    "source_type": "simulator",
                    "reliability_tier": "unknown",
                },
            ]
        },
    )

    assert response.status_code == 202
    assert response.json()["accepted_count"] == 2

    list_response = client.get(f"/patients/{patient_id}/observations", headers=auth_headers(patient_id, "observations:read"))
    filtered_response = client.get(
        f"/patients/{patient_id}/observations?metric_code=heart_rate",
        headers=auth_headers(patient_id, "observations:read"),
    )
    observation_id = filtered_response.json()["items"][0]["id"]
    get_response = client.get(
        f"/patients/{patient_id}/observations/{observation_id}",
        headers=auth_headers(patient_id, "observations:read"),
    )
    latest_response = client.get(f"/patients/{patient_id}/vitals/latest", headers=auth_headers(patient_id, "observations:read"))

    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 2
    assert filtered_response.status_code == 200
    assert filtered_response.json()["items"][0]["metric_code"] == "heart_rate"
    assert get_response.status_code == 200
    assert get_response.json()["value"] == 92
    assert latest_response.status_code == 200
    assert {reading["metric_code"] for reading in latest_response.json()["readings"]} == {"heart_rate", "spo2"}
