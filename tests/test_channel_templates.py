from pathlib import Path

from app.domain.channels import Channel, DispatchRequest, DispatchStatus, MessageTemplate, MessageTemplateStatus
from app.services.channels import ChannelDispatcher, TemplateLibrary, default_mock_adapters


ROOT = Path(__file__).resolve().parents[1]


def library() -> TemplateLibrary:
    return TemplateLibrary.from_paths(ROOT / "templates" / "messages", ROOT / "templates" / "calls")


def test_message_template_rendering_and_idempotency():
    dispatcher = ChannelDispatcher(library(), default_mock_adapters())
    request = DispatchRequest(
        patient_id="patient-1",
        channel=Channel.WHATSAPP,
        template_id="urgent_vitals_alert_v1",
        variables={
            "patient_name": "Asha",
            "severity": "critical",
            "reason": "Heart rate dropped to 38 bpm",
            "ack_url": "https://careagent.example/ack/1",
        },
        reason="critical alert",
        policy_decision_id="decision-1",
        idempotency_key="message-key-1",
        simulation=True,
    )

    first = dispatcher.dispatch(request)
    second = dispatcher.dispatch(request)

    assert first is second
    assert first.status == DispatchStatus.SIMULATED
    assert "Heart rate dropped" in first.rendered_content.body


def test_direct_dispatch_without_policy_decision_is_denied():
    dispatcher = ChannelDispatcher(library(), default_mock_adapters())
    attempt = dispatcher.dispatch(
        DispatchRequest(
            patient_id="patient-1",
            channel=Channel.SMS,
            template_id="sms_fallback_alert_v1",
            variables={
                "patient_name": "Asha",
                "severity": "high",
                "reason": "Blood pressure is high",
                "ack_url": "https://careagent.example/ack/2",
            },
            reason="manual send",
            policy_decision_id=None,
            idempotency_key="message-key-2",
            simulation=True,
        )
    )

    assert attempt.status == DispatchStatus.POLICY_DENIED
    assert attempt.error_code == "missing_policy_decision"


def test_whatsapp_business_template_must_be_approved():
    pending = MessageTemplate(
        id="pending_wa",
        channel=Channel.WHATSAPP,
        category="escalation",
        body="Alert {reason}",
        variables=("reason",),
        business_initiated=True,
        requires_approval=True,
        status=MessageTemplateStatus.PENDING_APPROVAL,
    )
    templates = TemplateLibrary([pending], [])
    dispatcher = ChannelDispatcher(templates, default_mock_adapters(simulation=False))

    attempt = dispatcher.dispatch(
        DispatchRequest(
            patient_id="patient-1",
            channel=Channel.WHATSAPP,
            template_id="pending_wa",
            variables={"reason": "urgent vitals"},
            reason="urgent vitals",
            policy_decision_id="decision-2",
            idempotency_key="message-key-3",
            simulation=False,
        )
    )

    assert attempt.status == DispatchStatus.POLICY_DENIED
    assert "not approved" in attempt.error_message


def test_voice_script_includes_ai_disclosure():
    content = library().render_call_script(
        "critical_escalation_ai_call_v1",
        {"patient_name": "Asha", "severity": "critical", "reason": "SpO2 is 82 percent"},
    )

    assert content.channel == Channel.VOICE
    assert "AI assistant" in content.body

