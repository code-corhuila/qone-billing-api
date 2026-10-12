"""What the billing service offers (Annex C, inbound ports): the operations BI-02..BI-06 of
the contract as commands, queries and a use-case interface. The HTTP adapter depends on this
module only; the use case implements it."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from billing.application.port.inbound.caller import Caller
from billing.domain.model.invoice import Invoice

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True)
class IssueInvoice:
    student_id: UUID
    student_name: str
    term: str
    amount_cents: int


@dataclass(frozen=True)
class Issued:
    invoice: Invoice
    created: bool
    """False when the Idempotency-Key had been used: the invoice is the one created first."""


@dataclass(frozen=True)
class Page:
    items: list[Invoice]
    page: int
    limit: int
    total: int

    @property
    def total_pages(self) -> int:
        return -(-self.total // self.limit) if self.total else 0


class InvoiceUseCases(Protocol):
    def issue(self, caller: Caller, command: IssueInvoice, idempotency_key: str) -> Issued:
        """BI-04, ADMIN. Idempotent by key; INV-BIL-001 is a BusinessRuleViolation."""

    def my_invoices(self, caller: Caller, term: str | None, page: int, limit: int) -> Page:
        """BI-02, STUDENT. Newest first; `limit` 1..100, 20 by default."""

    def get(self, caller: Caller, invoice_id: UUID) -> Invoice:
        """BI-03. The owner, an ADMIN or a SERVICE; another student's invoice is NotFound (D-03)."""

    def pay(self, caller: Caller, invoice_id: UUID) -> Invoice:
        """BI-05, the owner. Pays exactly once; a PAID invoice comes back unchanged (D-04)."""

    def current_of(self, caller: Caller, student_id: UUID) -> Invoice:
        """BI-06, ADMIN or SERVICE: the invoice of the current term, NotFound when none."""
