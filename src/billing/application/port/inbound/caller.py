"""Who calls a use case: the identity the HTTP adapter took from a validated token
(07-api/authentication.md). The role decides the operation; `user_id` decides ownership."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    STUDENT = "STUDENT"
    PROFESSOR = "PROFESSOR"
    ADMIN = "ADMIN"
    SERVICE = "SERVICE"


@dataclass(frozen=True)
class Caller:
    """`user_id` is the person's id; a SERVICE token carries the service name as subject and
    no user id (07-api/authentication.md: `sub` is the service name, never an app_user row)."""

    user_id: UUID | None
    role: Role
    name: str = ""
    subject: str = ""
