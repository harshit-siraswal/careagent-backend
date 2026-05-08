from __future__ import annotations

import os
from typing import Mapping

from app.agent.runtime import (
    DEFAULT_PROVIDER_ENDPOINTS,
    DEFAULT_PROVIDER_KEY_ENV_VARS,
    DEFAULT_PROVIDER_MODELS,
    AgentRuntimeAdapter,
    AgentRuntimeConfig,
    MockAgentRuntimeAdapter,
)


class AgentRuntimeConfigurationError(ValueError):
    pass


def build_agent_runtime_config(environ: Mapping[str, str] | None = None) -> AgentRuntimeConfig:
    source = os.environ if environ is None else environ
    provider = _read_env(source, "AGENT_RUNTIME_PROVIDER", "mock").lower()
    adapter_name = _read_env(source, "AGENT_RUNTIME_ADAPTER", "mock").lower()
    model = _read_env(source, "AGENT_RUNTIME_MODEL", "") or DEFAULT_PROVIDER_MODELS.get(provider, DEFAULT_PROVIDER_MODELS["custom"])
    api_key_env_var = _read_env(source, "AGENT_RUNTIME_API_KEY_ENV", "") or DEFAULT_PROVIDER_KEY_ENV_VARS.get(provider)
    endpoint_url = _read_env(source, "AGENT_RUNTIME_ENDPOINT_URL", "") or DEFAULT_PROVIDER_ENDPOINTS.get(provider)
    deployment_profile = _read_env(source, "AGENT_RUNTIME_PROFILE", "") or None

    return AgentRuntimeConfig(
        provider=provider,
        model=model,
        adapter_name=adapter_name,
        api_key_env_var=api_key_env_var,
        endpoint_url=endpoint_url,
        deployment_profile=deployment_profile,
        timeout_seconds=_read_float_env(source, "AGENT_RUNTIME_TIMEOUT_SECONDS", 30.0),
    )


def build_agent_runtime_adapter(config: AgentRuntimeConfig | None = None) -> AgentRuntimeAdapter:
    runtime_config = config or build_agent_runtime_config()
    if runtime_config.adapter_name != "mock":
        raise AgentRuntimeConfigurationError(
            f"Agent runtime adapter '{runtime_config.adapter_name}' is not implemented yet. "
            "Use AGENT_RUNTIME_ADAPTER=mock until a provider adapter is added."
        )
    return MockAgentRuntimeAdapter(runtime_config)


def _read_env(environ: Mapping[str, str], name: str, default: str) -> str:
    value = environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _read_float_env(environ: Mapping[str, str], name: str, default: float) -> float:
    value = _read_env(environ, name, "")
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise AgentRuntimeConfigurationError(f"{name} must be a number") from exc
