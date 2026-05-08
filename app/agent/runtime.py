from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, Sequence, runtime_checkable


AgentMessageRole = Literal["system", "user", "assistant", "tool"]

DEFAULT_PROVIDER_KEY_ENV_VARS: Mapping[str, str] = {
    "openclaw": "OPENCLAW_API_KEY",
    "nemoclaw": "NEMOCLAW_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
}

DEFAULT_PROVIDER_MODELS: Mapping[str, str] = {
    "mock": "mock-careagent-v0",
    "openclaw": "openclaw/default",
    "nemoclaw": "nemoclaw/default",
    "nvidia": "nvidia/default",
    "custom": "custom/default",
}

DEFAULT_PROVIDER_ENDPOINTS: Mapping[str, str] = {
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
