"""What the billing service needs (Annex C, outbound ports): the store of invoices with its
idempotency keys and outbox, a clock, an id generator and the payment provider. The adapters
implement them; the use cases know only these interfaces."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from billing.domain.model.events import DomainEvent
from billing.domain.model.invoice import Invoice


class DuplicateInvoice(Exception):
    """The store already holds an invoice for that student and term (the unique index of
    INV-BIL-001 fired under a race the use case's own check did not see)."""


class InvoiceStore(Protocol):
    def find_by_key(self, idempotency_key: str) -> Invoice | None:
        """The invoice an earlier request with this Idempotency-Key created, if any."""

    def exists(self, student_id: UUID, term: str) -> bool:
        """INV-BIL-001 pre-check."""

    def create(self, invoice: Invoice, idempotency_key: str, event: DomainEvent) -> tuple[Invoice, bool]:
        """Stores the invoice, its key and its event in ONE transaction (norm 5.3.8, 5.3.11).
        Returns (invoice, True), or (the invoice the key created first, False) when the key was
        already taken, in which case nothing new is kept. Raises DuplicateInvoice."""

    def find(self, invoice_id: UUID) -> Invoice | None: ...

    def find_current(self, student_id: UUID, term: str) -> Invoice | None: ...

    def page_of(self, student_id: UUID, term: str | None, page: int, limit: int) -> tuple[list[Invoice], int]:
        """The student's invoices newest first, one page, and the total count."""

    def save_paid(self, invoice: Invoice, event: DomainEvent) -> None:
        """Writes the paid invoice and its event in ONE transaction."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self) -> UUID: ...


class PaymentProvider(Protocol):
    def charge(self, invoice: Invoice) -> str:
        """Charges the invoice and returns the provider's reference (1 to 40 characters)."""
