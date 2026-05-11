from __future__ import annotations

import json
import string
import uuid
from pathlib import Path
from typing import Any, Protocol

from app.domain.channels import (
    CallScript,
    Channel,
    DispatchAttempt,
    DispatchRequest,
    DispatchStatus,
    MessageTemplate,
    MessageTemplateStatus,
    ProviderBehavior,
    ProviderConfig,
    ProviderEnvironment,
    ProviderKind,
    RenderedContent,
)
from app.core.config import Settings


class ProviderAdapter(Protocol):
    def dispatch(self, request: DispatchRequest, content: RenderedContent | None) -> DispatchAttempt:
        ...


class TemplateLibrary:
    def __init__(self, message_templates: list[MessageTemplate], call_scripts: list[CallScript]):
        self._messages = {template.id: template for template in message_templates}
        self._calls = {script.id: script for script in call_scripts}

    @classmethod
    def from_paths(cls, message_dir: str | Path, call_dir: str | Path) -> "TemplateLibrary":
        return cls(_load_messages(Path(message_dir)), _load_call_scripts(Path(call_dir)))

    def message_template(self, template_id: str) -> MessageTemplate:
        try:
            return self._messages[template_id]
        except KeyError as exc:
            raise KeyError(f"unknown message template {template_id}") from exc

    def call_script(self, script_id: str) -> CallScript:
        try:
            return self._calls[script_id]
        except KeyError as exc:
            raise KeyError(f"unknown call script {script_id}") from exc

    def render_message(
        self,
        template_id: str,
        variables: dict[str, str],
        *,
        simulation: bool = False,
    ) -> RenderedContent:
        template = self.message_template(template_id)
        template.validate_for_dispatch(simulation=simulation)
        missing = sorted(set(template.variables) - variables.keys())
        if missing:
            raise ValueError(f"missing template variables: {', '.join(missing)}")
        return RenderedContent(
            template_id=template.id,
            channel=template.channel,
            body=_render(template.body, variables),
            variables={key: variables[key] for key in template.variables},
        )

    def render_call_script(
        self,
        script_id: str,
        variables: dict[str, str],
    ) -> RenderedContent:
        script = self.call_script(script_id)
        script.validate_for_dispatch()
        missing = sorted(set(script.variables) - variables.keys())
        if missing:
            raise ValueError(f"missing call script variables: {', '.join(missing)}")
        body = "\n".join(
            [
                script.ai_disclosure.strip(),
                script.opening_text.strip(),
                _render(script.body_template, variables).strip(),
            ]
        )
        return RenderedContent(
            template_id=script.id,
            channel=Channel.VOICE,
            body=body,
            variables={key: variables[key] for key in script.variables},
        )


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._attempts: dict[str, DispatchAttempt] = {}

    def get(self, key: str) -> DispatchAttempt | None:
        return self._attempts.get(key)

    def put(self, key: str, attempt: DispatchAttempt) -> DispatchAttempt:
        self._attempts[key] = attempt
        return attempt


class MockProviderAdapter:
    def __init__(
        self,
        provider_config: ProviderConfig,
        *,
        behavior: ProviderBehavior = ProviderBehavior.DELIVER,
    ) -> None:
        provider_config.validate()
        self.provider_config = provider_config
        self.behavior = behavior
        self.invocations: list[DispatchRequest] = []

    def dispatch(self, request: DispatchRequest, content: RenderedContent | None) -> DispatchAttempt:
        self.invocations.append(request)
        status = {
            ProviderBehavior.DELIVER: DispatchStatus.DELIVERED,
            ProviderBehavior.ANSWER: DispatchStatus.ANSWERED,
            ProviderBehavior.ACKNOWLEDGE: DispatchStatus.ACKNOWLEDGED,
            ProviderBehavior.FAIL: DispatchStatus.FAILED,
            ProviderBehavior.TIMEOUT: DispatchStatus.EXPIRED,
        }[self.behavior]
        if request.simulation and status not in {DispatchStatus.ACKNOWLEDGED, DispatchStatus.EXPIRED}:
            status = DispatchStatus.SIMULATED
        attempt = DispatchAttempt(
            id=str(uuid.uuid4()),
            patient_id=request.patient_id,
            channel=request.channel,
            status=status,
            idempotency_key=request.idempotency_key,
            simulation=request.simulation,
            provider_config_id=self.provider_config.id,
            rendered_content=content,
        )
        if request.channel == Channel.VOICE:
            attempt.provider_call_id = f"mock_call_{attempt.id}"
        else:
            attempt.provider_message_id = f"mock_msg_{attempt.id}"
        return attempt


class ChannelDispatcher:
    def __init__(
        self,
        template_library: TemplateLibrary,
        adapters: dict[Channel, ProviderAdapter],
        *,
        idempotency_store: InMemoryIdempotencyStore | None = None,
    ) -> None:
        self.template_library = template_library
        self.adapters = adapters
        self.idempotency_store = idempotency_store or InMemoryIdempotencyStore()

    def dispatch(self, request: DispatchRequest) -> DispatchAttempt:
        previous = self.idempotency_store.get(request.idempotency_key)
        if previous is not None:
            return previous
        if not request.policy_decision_id:
            attempt = self._denied_attempt(request, "missing_policy_decision", "external action requires policy_decision_id")
            return self.idempotency_store.put(request.idempotency_key, attempt)
        try:
            content = self._render_content(request)
            adapter = self.adapters[request.channel]
            attempt = adapter.dispatch(request, content)
        except PermissionError as exc:
            attempt = self._denied_attempt(request, "policy_denied", str(exc))
        except KeyError as exc:
            attempt = self._denied_attempt(request, "provider_or_template_missing", str(exc))
        return self.idempotency_store.put(request.idempotency_key, attempt)

    def _render_content(self, request: DispatchRequest) -> RenderedContent | None:
        if request.channel == Channel.VOICE:
            if not request.script_id:
                raise PermissionError("voice dispatch requires script_id")
            return self.template_library.render_call_script(request.script_id, request.variables)
        if request.template_id:
            content = self.template_library.render_message(
                request.template_id,
                request.variables,
                simulation=request.simulation,
            )
            if content.channel != request.channel:
                raise PermissionError("template channel does not match dispatch channel")
            return content
        return None

    def _denied_attempt(self, request: DispatchRequest, code: str, message: str) -> DispatchAttempt:
        return DispatchAttempt(
            id=str(uuid.uuid4()),
            patient_id=request.patient_id,
            channel=request.channel,
            status=DispatchStatus.POLICY_DENIED,
            idempotency_key=request.idempotency_key,
            simulation=request.simulation,
            provider_config_id="policy",
            error_code=code,
            error_message=message,
        )


def default_mock_adapters(*, simulation: bool = True) -> dict[Channel, MockProviderAdapter]:
    environment = ProviderEnvironment.SIMULATION if simulation else ProviderEnvironment.SANDBOX
    return {
        Channel.PUSH: MockProviderAdapter(ProviderConfig("mock_push", Channel.PUSH, ProviderKind.MOCK_SIMULATOR, environment)),
        Channel.WHATSAPP: MockProviderAdapter(ProviderConfig("mock_whatsapp", Channel.WHATSAPP, ProviderKind.MOCK_SIMULATOR, environment)),
        Channel.TELEGRAM: MockProviderAdapter(ProviderConfig("mock_telegram", Channel.TELEGRAM, ProviderKind.MOCK_SIMULATOR, environment)),
        Channel.SMS: MockProviderAdapter(ProviderConfig("mock_sms", Channel.SMS, ProviderKind.MOCK_SIMULATOR, environment)),
        Channel.EMAIL: MockProviderAdapter(ProviderConfig("mock_email", Channel.EMAIL, ProviderKind.MOCK_SIMULATOR, environment)),
        Channel.VOICE: MockProviderAdapter(ProviderConfig("mock_voice", Channel.VOICE, ProviderKind.MOCK_SIMULATOR, environment)),
    }


def configured_adapters(settings: Settings, *, simulation: bool = True) -> dict[Channel, ProviderAdapter]:
    adapters: dict[Channel, ProviderAdapter] = dict(default_mock_adapters(simulation=simulation))
    if settings.voice_provider_adapter != "make_mcp":
        return adapters

    from app.services.make_mcp import MakeMcpClient, MakeMcpVoiceAdapter

    adapters[Channel.VOICE] = MakeMcpVoiceAdapter(
        ProviderConfig(
            "make_mcp_voice",
            Channel.VOICE,
            ProviderKind.MOCK_SIMULATOR,
            ProviderEnvironment.SANDBOX,
            capabilities={"transport": "make_mcp"},
        ),
        client=MakeMcpClient(
            settings.make_mcp_server_url,
            settings.make_mcp_bearer_token,
            settings.make_mcp_timeout_seconds,
        ),
        call_tool_name=settings.make_mcp_call_tool_name,
        allow_real_calls=settings.make_mcp_allow_real_calls,
    )
    return adapters


def _render(template: str, variables: dict[str, str]) -> str:
    formatter = string.Formatter()
    used = [field_name for _, field_name, _, _ in formatter.parse(template) if field_name]
    missing = sorted(set(used) - variables.keys())
    if missing:
        raise ValueError(f"missing render variables: {', '.join(missing)}")
    return template.format(**variables)


def _load_messages(directory: Path) -> list[MessageTemplate]:
    templates: list[MessageTemplate] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        templates.append(
            MessageTemplate(
                id=data["id"],
                channel=Channel(data["channel"]),
                category=data["category"],
                body=data["body"],
                variables=tuple(data.get("variables", [])),
                locale=data.get("locale", "en-IN"),
                version=int(data.get("version", 1)),
                status=MessageTemplateStatus(data.get("status", "approved")),
                provider_template_name=data.get("provider_template_name"),
                business_initiated=bool(data.get("business_initiated", False)),
                requires_approval=bool(data.get("requires_approval", False)),
                active=bool(data.get("active", True)),
            )
        )
    return templates


def _load_call_scripts(directory: Path) -> list[CallScript]:
    scripts: list[CallScript] = []
    for path in sorted(directory.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        scripts.append(
            CallScript(
                id=data["id"],
                opening_text=data["opening_text"],
                body_template=data["body_template"],
                ai_disclosure=data["ai_disclosure"],
                variables=tuple(data.get("variables", [])),
                locale=data.get("locale", "en-IN"),
                version=int(data.get("version", 1)),
                status=data.get("status", "approved"),
                dtmf_options=data.get("dtmf_options", {}),
                speech_intents=data.get("speech_intents", {}),
                max_duration_seconds=int(data.get("max_duration_seconds", 120)),
                recording_allowed=bool(data.get("recording_allowed", False)),
                transcript_allowed=bool(data.get("transcript_allowed", False)),
                active=bool(data.get("active", True)),
            )
        )
    return scripts

