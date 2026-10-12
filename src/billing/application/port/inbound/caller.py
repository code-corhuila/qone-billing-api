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
    user_id: UUID
    role: Role
    name: str = ""
