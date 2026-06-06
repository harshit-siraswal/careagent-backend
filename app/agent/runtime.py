from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence, runtime_checkable


AgentMessageRole = Literal["system", "user", "assistant", "tool"]

DEFAULT_PROVIDER_KEY_ENV_VARS: Mapping[str, str] = {
    "groq": "GROQ_API_KEY",
    "openclaw": "OPENCLAW_API_KEY",
    "nemoclaw": "NEMOCLAW_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
}

DEFAULT_PROVIDER_MODELS: Mapping[str, str] = {
    "mock": "mock-careagent-v0",
    "groq": "llama-3.3-70b-versatile",
    "openclaw": "openclaw/default",
    "nemoclaw": "nemoclaw/default",
    "nvidia": "nvidia/default",
    "custom": "custom/default",
}

DEFAULT_PROVIDER_ENDPOINTS: Mapping[str, str] = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openclaw": "http://127.0.0.1:18789",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}

REDACTED_VALUE = "<redacted>"
_SENSITIVE_KEY_NAMES = {
    "api_key",
    "authorization",
    "bearer_token",
    "client_secret",
    "credential",
    "credentials",
    "id_token",
    "password",
    "refresh_token",
    "secret",
    "token",
}
_SENSITIVE_KEY_SUFFIXES = (
    "_api_key",
    "_authorization",
    "_bearer_token",
    "_client_secret",
    "_credential",
    "_credentials",
    "_id_token",
    "_password",
    "_refresh_token",
    "_secret",
    "_token",
)


class AgentRuntimeContractError(ValueError):
    pass


class AgentRuntimeProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRuntimeMessage:
    role: AgentMessageRole
    content: str
    name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "metadata": redact_sensitive_mapping(self.metadata),
        }
        if self.name:
            payload["name"] = self.name
        return payload


@dataclass(frozen=True)
class AgentRuntimeRequest:
    request_id: str
    messages: Sequence[AgentRuntimeMessage]
    patient_id: str | None = None
    conversation_id: str | None = None
    tools: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRuntimeResponse:
    request_id: str
    provider: str
    model: str
    output_text: str
    tool_calls: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "output_text": self.output_text,
            "tool_calls": [redact_sensitive_mapping(tool_call) for tool_call in self.tool_calls],
            "metadata": redact_sensitive_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AgentRuntimeConfig:
    provider: str = "mock"
    model: str = DEFAULT_PROVIDER_MODELS["mock"]
    adapter_name: str = "mock"
    api_key_env_var: str | None = None
    endpoint_url: str | None = None
    deployment_profile: str | None = None
    timeout_seconds: float = 30.0
    extra: Mapping[str, Any] = field(default_factory=dict)

    def api_key_configured(self, environ: Mapping[str, str] | None = None) -> bool:
        if not self.api_key_env_var:
            return False
        source = os.environ if environ is None else environ
        return bool(source.get(self.api_key_env_var))

    def redacted_dict(self, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "adapter_name": self.adapter_name,
            "api_key_env_var": self.api_key_env_var,
            "api_key_configured": self.api_key_configured(environ),
            "endpoint_url": self.endpoint_url,
            "deployment_profile": self.deployment_profile,
            "timeout_seconds": self.timeout_seconds,
            "extra": redact_sensitive_mapping(self.extra),
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.redacted_dict()!r})"


@runtime_checkable
class AgentRuntimeAdapter(Protocol):
    @property
    def config(self) -> AgentRuntimeConfig:
        ...

    def generate(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        ...


class MockAgentRuntimeAdapter:
    """Deterministic no-network adapter for local tests and provider configuration dry-runs."""

    def __init__(self, config: AgentRuntimeConfig | None = None) -> None:
        self._config = config or AgentRuntimeConfig()

    @property
    def config(self) -> AgentRuntimeConfig:
        return self._config

    def generate(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        _validate_request(request)
        return AgentRuntimeResponse(
            request_id=request.request_id,
            provider=self.config.provider,
            model=self.config.model,
            output_text="Mock agent runtime response. No provider network call was made.",
            tool_calls=(),
            metadata={
                "adapter": self.config.adapter_name,
                "network": "disabled",
                "message_count": len(request.messages),
                "tool_count": len(request.tools),
                "provider_config": self.config.redacted_dict(),
            },
        )


GroqTransport = Callable[
    [str, str, Mapping[str, Any], float],
    Mapping[str, Any],
]


class GroqAgentRuntimeAdapter:
    """Groq chat-completion adapter using the OpenAI-compatible HTTP API."""

    def __init__(
        self,
        config: AgentRuntimeConfig | None = None,
        *,
        transport: GroqTransport | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._config = config or AgentRuntimeConfig(
            provider="groq",
            model=DEFAULT_PROVIDER_MODELS["groq"],
            adapter_name="groq",
            api_key_env_var=DEFAULT_PROVIDER_KEY_ENV_VARS["groq"],
            endpoint_url=DEFAULT_PROVIDER_ENDPOINTS["groq"],
        )
        self._transport = transport or _post_groq_chat_completion
        self._environ = os.environ if environ is None else environ

    @property
    def config(self) -> AgentRuntimeConfig:
        return self._config

    def generate(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        _validate_request(request)
        api_key = self._api_key()
        endpoint_url = self.config.endpoint_url or DEFAULT_PROVIDER_ENDPOINTS["groq"]
        payload = {
            "model": self.config.model,
            "messages": [_groq_message_payload(message) for message in request.messages],
            "temperature": float(self.config.extra.get("temperature", 0.2)),
            "max_completion_tokens": int(self.config.extra.get("max_completion_tokens", 512)),
            "tool_choice": "none",
        }
        response_payload = self._transport(endpoint_url, api_key, payload, self.config.timeout_seconds)
        output_text, tool_calls, finish_reason = _parse_groq_response(response_payload)

        return AgentRuntimeResponse(
            request_id=request.request_id,
            provider=self.config.provider,
            model=self.config.model,
            output_text=output_text,
            tool_calls=tool_calls,
            metadata={
                "adapter": self.config.adapter_name,
                "endpoint_url": endpoint_url,
                "finish_reason": finish_reason,
                "response_id": response_payload.get("id"),
                "usage": response_payload.get("usage", {}),
                "provider_config": self.config.redacted_dict(self._environ),
            },
        )

    def _api_key(self) -> str:
        if not self.config.api_key_env_var:
            raise AgentRuntimeProviderError("Groq runtime requires an API-key environment variable name")
        api_key = self._environ.get(self.config.api_key_env_var, "").strip()
        if not api_key:
            raise AgentRuntimeProviderError(f"{self.config.api_key_env_var} is not configured")
        return api_key


def redact_sensitive_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _redact_value(str(key), value) for key, value in values.items()}


def _redact_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return REDACTED_VALUE
    if isinstance(value, Mapping):
        return redact_sensitive_mapping(value)
    if isinstance(value, list | tuple):
        return [_redact_sequence_value(item) for item in value]
    return value


def _redact_sequence_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return redact_sensitive_mapping(value)
    if isinstance(value, list | tuple):
        return [_redact_sequence_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized.endswith("_env_var") or normalized.endswith("_env_vars"):
        return False
    return normalized in _SENSITIVE_KEY_NAMES or any(normalized.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def _validate_request(request: AgentRuntimeRequest) -> None:
    if not request.request_id:
        raise AgentRuntimeContractError("Agent runtime request requires request_id")
    if not request.messages:
        raise AgentRuntimeContractError("Agent runtime request requires at least one message")


def _groq_message_payload(message: AgentRuntimeMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }
    if message.name:
        payload["name"] = message.name
    return payload


def _parse_groq_response(payload: Mapping[str, Any]) -> tuple[str, Sequence[Mapping[str, Any]], str | None]:
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, str) or not choices:
        raise AgentRuntimeProviderError("Groq response did not include a chat completion choice")

    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise AgentRuntimeProviderError("Groq response choice was malformed")

    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise AgentRuntimeProviderError("Groq response did not include an assistant message")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise AgentRuntimeProviderError("Groq response did not include assistant text")

    raw_tool_calls = message.get("tool_calls", ())
    tool_calls: Sequence[Mapping[str, Any]]
    if isinstance(raw_tool_calls, Sequence) and not isinstance(raw_tool_calls, str):
        tool_calls = tuple(item for item in raw_tool_calls if isinstance(item, Mapping))
    else:
        tool_calls = ()

    finish_reason = first_choice.get("finish_reason")
    return content, tool_calls, finish_reason if isinstance(finish_reason, str) else None


def _post_groq_chat_completion(
    endpoint_url: str,
    api_key: str,
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        endpoint_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AgentRuntimeProviderError(f"Groq chat completion failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise AgentRuntimeProviderError("Groq chat completion request failed") from exc
    except TimeoutError as exc:
        raise AgentRuntimeProviderError("Groq chat completion request timed out") from exc
    except json.JSONDecodeError as exc:
        raise AgentRuntimeProviderError("Groq chat completion returned invalid JSON") from exc

    if not isinstance(response_payload, Mapping):
        raise AgentRuntimeProviderError("Groq chat completion returned an invalid payload")
    return response_payload
