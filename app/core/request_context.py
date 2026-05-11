from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DatabaseActorContext:
    user_id: UUID
    role: str


_database_actor_context: ContextVar[DatabaseActorContext | None] = ContextVar(
    "database_actor_context",
    default=None,
)


def set_database_actor_context(user_id: UUID, role: str) -> Token[DatabaseActorContext | None]:
    return _database_actor_context.set(DatabaseActorContext(user_id=user_id, role=role))


def reset_database_actor_context(token: Token[DatabaseActorContext | None]) -> None:
    _database_actor_context.reset(token)


def get_database_actor_context() -> DatabaseActorContext | None:
    return _database_actor_context.get()
