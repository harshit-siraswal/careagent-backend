from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.risk import FreshnessStatus, RiskSeverity
from app.services.risk_engine import (
    assess_observation_quality,
    evaluate_observations,
    make_escalation_idempotency_key,
    make_outbox_event_key,
    make_risk_event_idempotency_key,
    observation_from_mapping,
)


FIXTURE = Path(__file__).parent / "fixtures" / "device-simulator-scenarios.json"
PATIENT_ID = "11111111-1111-4111-8111-111111111111"
NOW = datetime.fromisoformat("2026-05-06T18:33:00+05:30")


def _scenario(code: str) -> dict:
    data = json.loads(FIXTURE.read_text())
    return next(item for item in data["scenarios"] if item["scenario_code"] == code)


def test_fresh_normal_day_has_no_risk_events() -> None:
    events = evaluate_observations(_scenario("fresh_normal_day_health_connect")["observations"], patient_id=PATIENT_ID, now=NOW)
    assert events == []


def test_critical_spo2_drop_outputs_evidence_and_policy_flags() -> None:
    events = evaluate_observations(_scenario("critical_spo2_drop_ble")["observations"], patient_id=PATIENT_ID, now=NOW)
    critical = [event for event in events if event.severity == RiskSeverity.CRITICAL]

    assert len(critical) == 1
    event = critical[0]
    assert "SpO2" in event.reason
    assert event.requires_policy_approval is True
    assert event.should_escalate_as_emergency is True
    assert event.evidence[0].quality.reliability_tier.value == "standard_ble"
    assert event.as_risk_event_create_request()["evidence"][0]["quality"]["freshness"] == "fresh"


def test_manual_low_glucose_requires_confirmation_not_critical_action() -> None:
    events = evaluate_observations(_scenario("manual_glucose_low_reliability")["observations"], patient_id=PATIENT_ID, now=NOW)

    assert len(events) == 1
    assert events[0].severity == RiskSeverity.HIGH
    assert events[0].requires_patient_confirmation is True
    assert events[0].recommended_action == "request_patient_confirmation"
    assert "manual_source" in events[0].evidence[0].quality.quality_flags


def test_stale_low_heart_rate_is_quality_event_not_emergency() -> None:
    events = evaluate_observations(_scenario("stale_watch_data_no_emergency")["observations"], patient_id=PATIENT_ID, now=NOW)

    assert {event.severity for event in events} == {RiskSeverity.LOW}
    assert all(event.should_escalate_as_emergency is False for event in events)
    assert any("stale" in event.reason for event in events)


def test_vendor_fall_event_is_critical_with_source_metadata() -> None:
    events = evaluate_observations(_scenario("fall_detected_vendor_event")["observations"], patient_id=PATIENT_ID, now=NOW)

    assert len(events) == 1
    assert events[0].severity == RiskSeverity.CRITICAL
    assert "fall" in events[0].reason.lower()
    assert events[0].requires_policy_approval is True
    assert events[0].evidence[0].quality.reliability_tier.value == "vendor_api"


def test_quality_assessment_matches_expected_fixture_bounds() -> None:
    observation = observation_from_mapping(_scenario("critical_spo2_drop_ble")["observations"][1], PATIENT_ID)
    quality = assess_observation_quality(observation, now=NOW)

    assert quality.freshness == FreshnessStatus.FRESH
    assert quality.quality_score >= 0.85


def test_idempotency_helpers_are_stable() -> None:
    observed_at = datetime.fromisoformat("2026-05-06T18:31:30+05:30")
    evidence = [{"metric": "spo2", "value": 86, "observed_at": observed_at.isoformat()}]

    key_one = make_risk_event_idempotency_key(PATIENT_ID, "spo2_critical_low", 1, observed_at, evidence)
    key_two = make_risk_event_idempotency_key(PATIENT_ID, "spo2_critical_low", 1, observed_at, evidence)

    assert key_one == key_two
    assert key_one.startswith(f"risk:{PATIENT_ID}:spo2_critical_low:v1:")
    assert make_outbox_event_key("risk_event.created", "risk-1", PATIENT_ID) == f"risk_event.created:{PATIENT_ID}:risk-1"
    assert make_escalation_idempotency_key("risk-1", "policy-1") == "escalation:risk-1:policy-1"
