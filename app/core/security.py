from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import Header, HTTPException, Request


ALL_PERMISSIONS = {
    "patient:read",
    "patient:write",
    "care_team:read",
    "care_team:write",
    "consent:read",
    "consent:write",
    "devices:read",
    "devices:write",
    "observations:read",
    "observations:write",
    "documents:read",
    "documents:write",
    "medicines:read",
    "medicines:write",
    "risk:read",
    "risk:write",
    "alerts:read",
    "alerts:write",
    "escalation:read",
    "escalation:write",
    "agent:read",
    "agent:write",
    "agent:tool_call",
    "audit:read",
}


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    role: str
    permissions: set[str] = field(default_factory=set)
    patient_id: UUID | None = None
    request_id: str = ""


def current_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    x_careagent_actor_id: UUID | None = Header(default=None),
    x_careagent_role: str = Header(default="patient"),
    x_careagent_patient_id: UUID | None = Header(default=None),
    x_careagent_permissions: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> Actor:
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "Bearer token is required."},
        )
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_authorization_header", "message": "Use a Bearer token."},
        )

    permissions = _parse_permissions(x_careagent_permissions)
    if x_careagent_role in {"admin", "system"}:
        permissions.add("patient:*")
        permissions.update(ALL_PERMISSIONS)

    actor = Actor(
        user_id=x_careagent_actor_id or uuid4(),
        role=x_careagent_role,
        permissions=permissions,
        patient_id=x_careagent_patient_id,
        request_id=x_request_id or str(uuid4()),
    )
    request.state.actor = actor
    return actor


def optional_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    x_careagent_actor_id: UUID | None = Header(default=None),
    x_careagent_role: str = Header(default="patient"),
    x_careagent_patient_id: UUID | None = Header(default=None),
    x_careagent_permissions: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> Actor:
    if authorization is None:
        actor = Actor(
            user_id=x_careagent_actor_id or uuid4(),
            role=x_careagent_role,
            permissions=set(),
            patient_id=x_careagent_patient_id,
            request_id=x_request_id or str(uuid4()),
        )
        request.state.actor = actor
        return actor
    return current_actor(
        request,
        authorization,
        x_careagent_actor_id,
        x_careagent_role,
        x_careagent_patient_id,
        x_careagent_permissions,
        x_request_id,
    )


def require_patient_scope(actor: Actor, patient_id: UUID, permission: str) -> None:
    allowed = (
        actor.role == "admin"
        or "patient:*" in actor.permissions
        or permission in actor.permissions
        or (actor.role == "patient" and actor.patient_id == patient_id)
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "patient_scope_denied",
                "message": "Actor lacks patient scope or required permission.",
                "details": {"patient_id": str(patient_id), "permission": permission},
            },
        )


def require_permission(actor: Actor, permission: str) -> None:
    if actor.role == "admin" or "patient:*" in actor.permissions or permission in actor.permissions:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "permission_denied",
            "message": "Actor lacks required permission.",
            "details": {"permission": permission},
        },
    )


def _parse_permissions(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}
