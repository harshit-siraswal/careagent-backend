from __future__ import annotations

from app.domain.channels import (
    Channel,
    DispatchRequest,
    DispatchStatus,
    ProviderConfig,
    ProviderEnvironment,
    ProviderKind,
    RenderedContent,
)
from app.services.make_mcp import MakeMcpVoiceAdapter, parse_mcp_response


class FakeMakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {
            "structuredContent": {"call_id": "call_123"},
            "content": [{"type": "text", "text": "queued"}],
        }


def provider_config() -> ProviderConfig:
    return ProviderConfig(
        "make_mcp_voice",
        Channel.VOICE,
        ProviderKind.MOCK_SIMULATOR,
        ProviderEnvironment.SANDBOX,
    )


def voice_request(*, simulation: bool) -> DispatchRequest:
    return DispatchRequest(
        patient_id="patient-1",
        channel=Channel.VOICE,
        variables={"patient_name": "Asha", "phone_e164": "+15555550100"},
        reason="Critical vitals need caretaker acknowledgement.",
        policy_decision_id="policy:1:step:1",
        idempotency_key="voice-1",
        contact_id="primary",
        escalation_run_id="run-1",
        escalation_action_id="action-1",
        script_id="critical_escalation_ai_call_v1",
        simulation=simulation,
    )


def rendered_content() -> RenderedContent:
    return RenderedContent(
        template_id="critical_escalation_ai_call_v1",
        channel=Channel.VOICE,
        body="AI assistant calling about critical vitals.",
        variables={"patient_name": "Asha"},
    )


def test_parse_mcp_sse_response() -> None:
    parsed = parse_mcp_response(
        'event: message\n'
        'data: {"result":{"tools":[{"name":"place_call"}]},"jsonrpc":"2.0","id":2}\n\n'
    )

    assert parsed["result"]["tools"][0]["name"] == "place_call"


def test_make_mcp_voice_adapter_dispatches_simulation_call() -> None:
    client = FakeMakeClient()
    adapter = MakeMcpVoiceAdapter(
        provider_config(),
        client=client,
        call_tool_name="place_call",
    )

    attempt = adapter.dispatch(voice_request(simulation=True), rendered_content())

    assert attempt.status == DispatchStatus.SIMULATED
    assert attempt.provider_call_id == "call_123"
    assert client.calls[0][0] == "place_call"
    assert client.calls[0][1]["event"] == "careagent.voice_call.requested"
    assert client.calls[0][1]["simulation"] is True
    assert client.calls[0][1]["target"]["phone_e164"] == "+15555550100"


def test_make_mcp_voice_adapter_denies_real_calls_by_default() -> None:
    client = FakeMakeClient()
    adapter = MakeMcpVoiceAdapter(
        provider_config(),
        client=client,
        call_tool_name="place_call",
    )

    attempt = adapter.dispatch(voice_request(simulation=False), rendered_content())

    assert attempt.status == DispatchStatus.POLICY_DENIED
    assert attempt.error_code == "make_mcp_real_calls_disabled"
    assert client.calls == []
