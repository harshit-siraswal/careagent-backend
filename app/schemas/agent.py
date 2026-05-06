from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.schemas.common import ContactChannel


class AgentMessageRequest(BaseModel):
    patient_id: UUID
    conversation_id: UUID | None = None
    channel: ContactChannel
    message: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class AgentMessageResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID = Field(default_factory=uuid4)
    response: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    audit_log_id: UUID


class AgentToolRequest(BaseModel):
    patient_id: UUID
    actor_id: UUID | None = None
    request_id: str
    authorization_scope: str
    reason: str
    input: dict[str, Any]


class AgentToolResponse(BaseModel):
    status: Literal["ok", "denied", "error"] = "ok"
    result: dict[str, Any] = Field(default_factory=dict)
    audit_log_id: UUID
    safe_user_message: str | None = None
    error_code: str | None = None
