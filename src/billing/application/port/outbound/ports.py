"""What the billing service needs (Annex C, outbound ports): the store of invoices with its
idempotency keys and outbox, a clock, an id generator and the payment provider. The adapters
implement them; the use cases know only these interfaces."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from billing.domain.model.events import DomainEvent
from billing.domain.model.invoice import Invoice


class DuplicateInvoice(Exception):
    """The store already holds an invoice for that student and term (the unique index of
    INV-BIL-001 fired under a race the use case's own check did not see)."""


@dataclass(frozen=True)
class IdempotencyClaim:
    """An Idempotency-Key as its owner sent it: the key is scoped to the owner (the user id of
    the token, or the SERVICE subject), so the same key from another caller is another key, and
    `request_hash` is the SHA-256 (hex) of the canonical request body it was first used with."""

    owner: str
    key: str
    request_hash: str


class InvoiceStore(Protocol):
    def find_by_key(self, owner: str, idempotency_key: str) -> tuple[Invoice, str] | None:
        """The invoice an earlier request of this owner with this key created, and the hash of
        that request's body; None when this owner never used the key."""

    def exists(self, student_id: UUID, term: str) -> bool:
        """INV-BIL-001 pre-check."""

    def create(self, invoice: Invoice, claim: IdempotencyClaim, event: DomainEvent) -> tuple[Invoice, bool]:
        """Stores the invoice, its claimed key and its event in ONE transaction (norm 5.3.8,
        5.3.11). Returns (invoice, True), or (the invoice the owner's key created first, False)
        when the owner had already used the key, in which case nothing new is kept. Raises
        DuplicateInvoice."""

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


class DependencyProbe(Protocol):
    """A dependency the service needs to take traffic (HU-PLT-004): `ping` returns when it answers
    within the adapter's short timeout and raises otherwise."""

    name: str

    def ping(self) -> None: ...
