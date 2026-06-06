from __future__ import annotations

import json

import pytest

from app.agent.runtime import (
    REDACTED_VALUE,
    AgentRuntimeAdapter,
    AgentRuntimeConfig,
    AgentRuntimeContractError,
    AgentRuntimeMessage,
    AgentRuntimeProviderError,
    AgentRuntimeRequest,
    GroqAgentRuntimeAdapter,
    MockAgentRuntimeAdapter,
    redact_sensitive_mapping,
)
from app.services.agent_runtime import (
    AgentRuntimeConfigurationError,
    build_agent_runtime_adapter,
    build_agent_runtime_config,
)


def _request() -> AgentRuntimeRequest:
    return AgentRuntimeRequest(
        request_id="agent-runtime-test-1",
        patient_id="11111111-1111-4111-8111-111111111111",
        messages=(
            AgentRuntimeMessage(role="system", content="Follow CareAgent policy."),
            AgentRuntimeMessage(role="user", content="What should I do next?"),
        ),
        tools=({"name": "get_recent_vitals"},),
    )


def test_mock_adapter_satisfies_protocol_and_never_calls_network() -> None:
    config = AgentRuntimeConfig(provider="nvidia", model="nvidia/default", adapter_name="mock", api_key_env_var="NVIDIA_API_KEY")
    adapter = MockAgentRuntimeAdapter(config)

    assert isinstance(adapter, AgentRuntimeAdapter)

    response = adapter.generate(_request())
    payload = response.as_dict()

    assert response.provider == "nvidia"
    assert response.model == "nvidia/default"
    assert payload["output_text"] == "Mock agent runtime response. No provider network call was made."
    assert payload["tool_calls"] == []
    assert payload["metadata"]["network"] == "disabled"
    assert payload["metadata"]["message_count"] == 2


def test_runtime_contract_requires_request_id_and_messages() -> None:
    adapter = MockAgentRuntimeAdapter()

    with pytest.raises(AgentRuntimeContractError, match="request_id"):
        adapter.generate(AgentRuntimeRequest(request_id="", messages=_request().messages))

    with pytest.raises(AgentRuntimeContractError, match="at least one message"):
        adapter.generate(AgentRuntimeRequest(request_id="req-1", messages=()))


def test_provider_config_uses_key_env_var_name_without_leaking_secret_value() -> None:
    secret = "example-nvidia-secret-value-that-must-not-leak"
    environ = {
        "AGENT_RUNTIME_PROVIDER": "nvidia",
        "AGENT_RUNTIME_MODEL": "nvidia/default",
        "NVIDIA_API_KEY": secret,
    }

    config = build_agent_runtime_config(environ)
    payload = config.redacted_dict(environ)
    serialized = json.dumps(payload, sort_keys=True) + repr(config)

    assert config.api_key_env_var == "NVIDIA_API_KEY"
    assert payload["api_key_configured"] is True
    assert "NVIDIA_API_KEY" in serialized
    assert secret not in serialized


def test_openclaw_provider_uses_local_gateway_target_without_requiring_secret() -> None:
    config = build_agent_runtime_config({"AGENT_RUNTIME_PROVIDER": "openclaw"})
    payload = config.redacted_dict({})

    assert config.provider == "openclaw"
    assert config.model == "openclaw/default"
    assert config.endpoint_url == "http://127.0.0.1:18789"
    assert config.api_key_env_var == "OPENCLAW_API_KEY"
    assert payload["api_key_configured"] is False


def test_groq_provider_uses_groq_defaults_without_leaking_secret_value() -> None:
    secret = "example-groq-secret-value-that-must-not-leak"
    environ = {
        "AGENT_RUNTIME_PROVIDER": "groq",
        "AGENT_RUNTIME_ADAPTER": "groq",
        "GROQ_API_KEY": secret,
    }

    config = build_agent_runtime_config(environ)
    payload = config.redacted_dict(environ)
    serialized = json.dumps(payload, sort_keys=True) + repr(config)

    assert config.provider == "groq"
    assert config.adapter_name == "groq"
    assert config.model == "llama-3.3-70b-versatile"
    assert config.endpoint_url == "https://api.groq.com/openai/v1/chat/completions"
    assert config.api_key_env_var == "GROQ_API_KEY"
    assert payload["api_key_configured"] is True
    assert "GROQ_API_KEY" in serialized
    assert secret not in serialized


def test_secret_like_fields_are_redacted_but_env_var_names_are_visible() -> None:
    secret = "example-openclaw-secret-value-that-must-not-leak"

    redacted = redact_sensitive_mapping(
        {
            "OPENCLAW_API_KEY": secret,
            "authorization_scope": "agent:tool_call",
            "api_key_env_var": "OPENCLAW_API_KEY",
            "nested": {"access_token": secret},
        }
    )
    serialized = json.dumps(redacted, sort_keys=True)

    assert redacted["OPENCLAW_API_KEY"] == REDACTED_VALUE
    assert redacted["authorization_scope"] == "agent:tool_call"
    assert redacted["api_key_env_var"] == "OPENCLAW_API_KEY"
    assert redacted["nested"]["access_token"] == REDACTED_VALUE
    assert secret not in serialized


def test_factory_keeps_unimplemented_network_adapters_disabled() -> None:
    config = AgentRuntimeConfig(provider="nvidia", model="nvidia/default", adapter_name="nvidia", api_key_env_var="NVIDIA_API_KEY")

    with pytest.raises(AgentRuntimeConfigurationError, match="not implemented"):
        build_agent_runtime_adapter(config)

    adapter = build_agent_runtime_adapter(AgentRuntimeConfig(provider="openclaw", model="openclaw/default", adapter_name="mock"))

    assert isinstance(adapter, MockAgentRuntimeAdapter)


def test_factory_builds_groq_adapter_when_explicitly_selected() -> None:
    config = AgentRuntimeConfig(
        provider="groq",
        model="llama-3.3-70b-versatile",
        adapter_name="groq",
        api_key_env_var="GROQ_API_KEY",
        endpoint_url="https://api.groq.com/openai/v1/chat/completions",
    )

    adapter = build_agent_runtime_adapter(config)

    assert isinstance(adapter, GroqAgentRuntimeAdapter)


def test_groq_adapter_requires_configured_key() -> None:
    adapter = GroqAgentRuntimeAdapter(
        AgentRuntimeConfig(
            provider="groq",
            model="llama-3.3-70b-versatile",
            adapter_name="groq",
            api_key_env_var="GROQ_API_KEY",
            endpoint_url="https://api.groq.com/openai/v1/chat/completions",
        ),
        environ={},
    )

    with pytest.raises(AgentRuntimeProviderError, match="GROQ_API_KEY"):
        adapter.generate(_request())


def test_groq_adapter_maps_chat_completion_response_without_leaking_secret() -> None:
    secret = "example-groq-secret-value-that-must-not-leak"
    calls: list[dict[str, object]] = []

    def fake_transport(
        endpoint_url: str,
        api_key: str,
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        calls.append(
            {
                "endpoint_url": endpoint_url,
                "api_key": api_key,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "id": "chatcmpl-test",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Track symptoms, follow your care plan, and contact local emergency services for urgent symptoms.",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 9,
                "total_tokens": 21,
            },
        }

    adapter = GroqAgentRuntimeAdapter(
        AgentRuntimeConfig(
            provider="groq",
            model="llama-3.3-70b-versatile",
            adapter_name="groq",
            api_key_env_var="GROQ_API_KEY",
            endpoint_url="https://api.groq.com/openai/v1/chat/completions",
            timeout_seconds=7.0,
        ),
        transport=fake_transport,
        environ={"GROQ_API_KEY": secret},
    )

    response = adapter.generate(_request())
    serialized_response = json.dumps(response.as_dict(), sort_keys=True)
    payload = calls[0]["payload"]

    assert response.output_text.startswith("Track symptoms")
    assert calls[0]["endpoint_url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert calls[0]["api_key"] == secret
    assert calls[0]["timeout_seconds"] == 7.0
    assert payload["model"] == "llama-3.3-70b-versatile"
    assert payload["tool_choice"] == "none"
    assert response.metadata["finish_reason"] == "stop"
    assert secret not in serialized_response
