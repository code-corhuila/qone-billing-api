"""Typed errors of the billing domain.

The domain raises these; it does not know HTTP. The inbound HTTP adapter translates each one
to a status code and the error envelope in one place (Annex C). A message that enforces a
documented invariant starts with its identifier (INV-BIL-001) so a test, a log line and a
screenshot trace to 02-domain.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldError:
    field: str
    message: str


class DomainError(Exception):
    """Base of every error the domain raises."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class ValidationError(DomainError):
    """The shape of the input is invalid: one entry per field."""

    details: list[FieldError] = field(default_factory=list)

    def __init__(self, details: list[FieldError]) -> None:
        super().__init__("the request has invalid fields")
        self.details = details


class BusinessRuleViolation(DomainError):
    """An invariant of the domain forbids the operation (INV-BIL-001)."""
