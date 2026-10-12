"""The Invoice aggregate (02-domain, 06-data/models.md schema billing).

Pure Python: no framework, no driver (Annex C dependency rule). Money is an integer in COP
cents end to end (norm 5.4.3). Invariants kept here:

- INV-BIL-002: PAID is terminal. `pay` on a PAID invoice is a no-op that returns the same
  invoice (D-04), never a second payment.
- The shape of an invoice: name 2..120 characters, term `YYYY-A|B`, amount > 0, integer.

INV-BIL-001 (one invoice per student and term) needs the whole collection: the use case checks
it and the database's unique index is the last line (modeling-conventions.md).
"""

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from billing.domain.model.errors import FieldError, ValidationError

TERM_PATTERN = re.compile(r"^[0-9]{4}-[AB]$")
PROVIDER_REFERENCE_MAX = 40


class InvoiceStatus(StrEnum):
    ISSUED = "ISSUED"
    PAID = "PAID"


@dataclass(frozen=True)
class Invoice:
    id: UUID
    student_id: UUID
    student_name: str
    term: str
    amount_cents: int
    status: InvoiceStatus
    provider_reference: str | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def issue(
        invoice_id: UUID,
        student_id: UUID,
        student_name: str,
        term: str,
        amount_cents: int,
        now: datetime,
    ) -> "Invoice":
        """A new ISSUED invoice, or ValidationError with one entry per invalid field."""
        details: list[FieldError] = []
        name = student_name.strip() if isinstance(student_name, str) else ""
        if not 2 <= len(name) <= 120:
            details.append(FieldError("studentName", "must have 2 to 120 characters"))
        if not isinstance(term, str) or not TERM_PATTERN.match(term):
            details.append(FieldError("term", "must match ^[0-9]{4}-[AB]$"))
        if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents <= 0:
            details.append(FieldError("amountCents", "must be a positive integer in cents"))
        if details:
            raise ValidationError(details)
        moment = _utc(now)
        return Invoice(
            id=invoice_id,
            student_id=student_id,
            student_name=name,
            term=term,
            amount_cents=amount_cents,
            status=InvoiceStatus.ISSUED,
            provider_reference=None,
            paid_at=None,
            created_at=moment,
            updated_at=moment,
        )

    @property
    def is_paid(self) -> bool:
        return self.status is InvoiceStatus.PAID

    def pay(self, provider_reference: str, now: datetime) -> tuple["Invoice", bool]:
        """Moves ISSUED to PAID exactly once. Returns (invoice, changed): a PAID invoice comes
        back unchanged with changed=False (INV-BIL-002, D-04)."""
        if self.is_paid:
            return self, False
        if not provider_reference or len(provider_reference) > PROVIDER_REFERENCE_MAX:
            raise ValueError("provider reference must have 1 to 40 characters")
        moment = _utc(now)
        paid = replace(
            self,
            status=InvoiceStatus.PAID,
            provider_reference=provider_reference,
            paid_at=moment,
            updated_at=moment,
        )
        return paid, True


def _utc(moment: datetime) -> datetime:
    """The domain keeps aware UTC instants; a naive datetime is taken as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
