from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from pydantic import BaseModel, Field

from app.core.security import Actor


class AuditEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    actor_type: str = "user"
    actor_id: str | None = None
    actor_user_id: UUID | None = None
    patient_id: UUID | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    outcome: str = "success"
    phi_access: bool = False
    reason: str | None = None
    request_id: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def audit(
    request: Request,
    *,
    actor: Actor,
    action: str,
    resource_type: str,
    patient_id: UUID | None = None,
    resource_id: UUID | str | None = None,
    phi_access: bool = False,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UUID:
    event = AuditEvent(
        actor_id=str(actor.user_id),
        actor_user_id=actor.user_id,
        patient_id=patient_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        phi_access=phi_access,
        reason=reason,
        request_id=actor.request_id,
        metadata_json=metadata or {},
    )
    events = getattr(request.state, "audit_events", None)
    if events is None:
        events = []
        request.state.audit_events = events
    events.append(event)
    return event.id
