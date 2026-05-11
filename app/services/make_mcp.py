from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.domain.channels import (
    Channel,
    DispatchAttempt,
    DispatchRequest,
    DispatchStatus,
    ProviderConfig,
    RenderedContent,
)


class MakeMcpError(RuntimeError):
    pass


@dataclass(frozen=True)
class MakeMcpClient:
    server_url: str
    bearer_token: str
    timeout_seconds: int = 20

    def initialize(self) -> dict[str, Any]:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "careagent-backend", "version": "0.1.0"},
                },
            }
        )
        return dict(response.get("result") or {})

    def list_tools(self) -> list[dict[str, Any]]:
        response = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        result = response.get("result") or {}
        return list(result.get("tools") or [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        return dict(response.get("result") or {})

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.server_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MakeMcpError(f"Make MCP HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise MakeMcpError(f"Make MCP connection failed: {exc.reason}") from exc

        parsed = parse_mcp_response(raw)
        if "error" in parsed:
            raise MakeMcpError(f"Make MCP error: {parsed['error']}")
        return parsed


class MakeMcpVoiceAdapter:
    def __init__(
        self,
        provider_config: ProviderConfig,
        *,
        client: MakeMcpClient,
        call_tool_name: str,
        allow_real_calls: bool = False,
    ) -> None:
        provider_config.validate()
        if provider_config.channel != Channel.VOICE:
            raise ValueError("Make MCP voice adapter requires a voice provider config")
        self.provider_config = provider_config
        self.client = client
        self.call_tool_name = call_tool_name
        self.allow_real_calls = allow_real_calls

    def dispatch(self, request: DispatchRequest, content: RenderedContent | None) -> DispatchAttempt:
        if request.channel != Channel.VOICE:
            raise PermissionError("Make MCP adapter only supports voice dispatch")
        if content is None:
            raise PermissionError("Make MCP voice dispatch requires rendered call content")
        if not request.simulation and not self.allow_real_calls:
            return DispatchAttempt(
                id=str(uuid.uuid4()),
                patient_id=request.patient_id,
                channel=request.channel,
                status=DispatchStatus.POLICY_DENIED,
                idempotency_key=request.idempotency_key,
                simulation=request.simulation,
                provider_config_id=self.provider_config.id,
                rendered_content=content,
                error_code="make_mcp_real_calls_disabled",
                error_message="Make MCP real calls are disabled until provider launch approval.",
            )

        tool_result = self.client.call_tool(self.call_tool_name, _call_arguments(request, content))
        provider_call_id = _provider_call_id(tool_result) or f"make_mcp:{uuid.uuid4()}"
        return DispatchAttempt(
            id=str(uuid.uuid4()),
            patient_id=request.patient_id,
            channel=request.channel,
            status=DispatchStatus.SIMULATED if request.simulation else DispatchStatus.PROVIDER_PENDING,
            idempotency_key=request.idempotency_key,
            simulation=request.simulation,
            provider_config_id=self.provider_config.id,
            rendered_content=content,
            provider_call_id=provider_call_id,
            metadata={
                "make_mcp_tool": self.call_tool_name,
                "make_mcp_content_items": len(tool_result.get("content") or []),
                "make_mcp_is_error": bool(tool_result.get("isError")),
            },
        )


def parse_mcp_response(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if not stripped:
        raise MakeMcpError("Make MCP returned an empty response")
    if stripped.startswith("{"):
        return dict(json.loads(stripped))

    data_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            data = line.removeprefix("data: ").strip()
            if data and data != "[DONE]":
                data_lines.append(data)
    if not data_lines:
        raise MakeMcpError("Make MCP response did not include JSON data")
    return dict(json.loads("".join(data_lines)))


def _call_arguments(request: DispatchRequest, content: RenderedContent) -> dict[str, Any]:
    return {
        "event": "careagent.voice_call.requested",
        "simulation": request.simulation,
        "patient_id": request.patient_id,
        "contact_id": request.contact_id,
        "target": {
            "contact_id": request.contact_id,
            "phone_e164": request.variables.get("phone_e164"),
        },
        "reason": request.reason,
        "locale": request.locale,
        "policy_decision_id": request.policy_decision_id,
        "idempotency_key": request.idempotency_key,
        "escalation_run_id": request.escalation_run_id,
        "escalation_action_id": request.escalation_action_id,
        "script_id": request.script_id,
        "template_id": content.template_id,
        "variables": request.variables,
        "call_script": content.body,
    }


def _provider_call_id(tool_result: dict[str, Any]) -> str | None:
    structured = tool_result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("call_id", "callId", "provider_call_id", "providerCallId", "id"):
            value = structured.get(key)
            if value:
                return str(value)
    return None
