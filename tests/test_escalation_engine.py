from pathlib import Path

from app.domain.channels import Channel, ChannelLink, VerificationStatus
from app.domain.escalation import (
    ConsentState,
    EscalationActionStatus,
    EscalationPolicy,
    EscalationPolicyStep,
    EscalationRunStatus,
    RiskEvent,
    RiskSeverity,
)
from app.services.channels import ChannelDispatcher, TemplateLibrary, default_mock_adapters
from app.services.escalation import EmergencySimulationRunner, EscalationEngine


ROOT = Path(__file__).resolve().parents[1]


def make_engine(links=None):
    templates = TemplateLibrary.from_paths(ROOT / "templates" / "messages", ROOT / "templates" / "calls")
    dispatcher = ChannelDispatcher(templates, default_mock_adapters())
    return EscalationEngine(dispatcher, channel_links=links or [])


def risk_event() -> RiskEvent:
    return RiskEvent(
        id="risk-1",
        patient_id="patient-1",
        severity=RiskSeverity.CRITICAL,
        reason="Heart rate dropped to 38 bpm",
    )


def policy() -> EscalationPolicy:
    return EscalationPolicy(
        id="policy-1",
        patient_id="patient-1",
        name="Critical fallback",
        severity_trigger=RiskSeverity.HIGH,
        simulation_mode=True,
        steps=(
            EscalationPolicyStep(1, "notify", Channel.PUSH, target_contact_id="primary", template_id="push_urgent_vitals_alert_v1"),
            EscalationPolicyStep(2, "call", Channel.VOICE, target_contact_id="primary", script_id="critical_escalation_ai_call_v1"),
            EscalationPolicyStep(3, "call", Channel.VOICE, target_contact_id="doctor", script_id="critical_escalation_ai_call_v1"),
        ),
    )


def test_escalation_replays_duplicate_start_without_duplicate_actions():
    engine = make_engine()

    first = engine.start(risk_event(), policy(), idempotency_key="idem-1")
    second = engine.start(risk_event(), policy(), idempotency_key="idem-1")

    assert first is second
    assert len(second.actions) == 3
    assert second.metadata["idempotency_replayed"] is True


def test_ordered_fallback_acknowledges_when_later_voice_step_acks():
    engine = make_engine()
    run = engine.start(
        risk_event(),
        policy(),
        idempotency_key="idem-2",
        provider_behaviors=[
            {"step_order": 1, "behavior": "deliver"},
            {"step_order": 2, "behavior": "timeout"},
            {"step_order": 3, "behavior": "acknowledge"},
        ],
    )

    assert run.status == EscalationRunStatus.ACKNOWLEDGED
    assert run.actions[1].status == EscalationActionStatus.FAILED
    assert run.actions[2].status == EscalationActionStatus.ACKNOWLEDGED


def test_revoked_voice_consent_skips_voice_but_continues_non_voice():
    engine = make_engine()
    run = engine.start(
        risk_event(),
        policy(),
        idempotency_key="idem-3",
        consent=ConsentState(voice_calls=False),
    )

    assert run.actions[0].status == EscalationActionStatus.DELIVERED
    assert run.actions[1].status == EscalationActionStatus.SKIPPED
    assert run.actions[1].error_code == "consent_denied"
    assert run.status == EscalationRunStatus.AWAITING_ACK


def test_unverified_telegram_ack_is_rejected():
    engine = make_engine()
    run = engine.start(risk_event(), policy(), idempotency_key="idem-4")

    ack = engine.acknowledge(
        run,
        acknowledgement_method="telegram_callback",
        channel=Channel.TELEGRAM,
        acknowledged_by_contact_id="primary",
    )

    assert ack is None
    assert run.status == EscalationRunStatus.AWAITING_ACK


def test_verified_telegram_ack_is_accepted():
    engine = make_engine(
        [
            ChannelLink(
                id="link-1",
                patient_id="patient-1",
                contact_id="primary",
                channel=Channel.TELEGRAM,
                external_subject_ref="chat-1",
                verification_status=VerificationStatus.VERIFIED,
            )
        ]
    )
    run = engine.start(risk_event(), policy(), idempotency_key="idem-5")

    ack = engine.acknowledge(
        run,
        acknowledgement_method="telegram_callback",
        channel=Channel.TELEGRAM,
        acknowledged_by_contact_id="primary",
    )

    assert ack is not None
    assert run.status == EscalationRunStatus.ACKNOWLEDGED


def test_location_is_omitted_without_consent():
    location_policy = EscalationPolicy(
        id="policy-location",
        patient_id="patient-1",
        name="Location policy",
        severity_trigger=RiskSeverity.CRITICAL,
        simulation_mode=True,
        steps=(
            EscalationPolicyStep(
                1,
                "notify",
                Channel.SMS,
                target_contact_id="primary",
                template_id="sms_fallback_alert_v1",
                include_location=True,
            ),
        ),
    )
    engine = make_engine()
    run = engine.start(risk_event(), location_policy, idempotency_key="idem-6", consent=ConsentState(location_sharing=False))

    assert run.actions[0].metadata["location_included"] is False
    assert run.status == EscalationRunStatus.AWAITING_ACK


def test_emergency_simulation_fixture_runs_without_production_provider_invocations():
    engine = make_engine()
    runner = EmergencySimulationRunner.from_fixture(engine, ROOT / "tests" / "emergency_simulation_cases.json")

    simulation = runner.run_case("critical_hr_no_ack_fallback", "patient-1")

    assert simulation.status.value == "passed"
    assert simulation.actual_summary["production_provider_invocations"] == 0
    assert simulation.escalation_run.status == EscalationRunStatus.ACKNOWLEDGED

