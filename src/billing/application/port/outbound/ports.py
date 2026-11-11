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


class PaymentDeclined(Exception):
    """The provider answered and refused the charge (insufficient funds, card refused): nothing
    was charged, so the invoice stays ISSUED and no TuitionPaid is written."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PaymentProviderUnavailable(Exception):
    """The provider did not answer (timeout, connection refused): the invoice stays ISSUED and
    the student may try again."""


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

    def save_paid(self, invoice: Invoice, event: DomainEvent) -> Invoice:
        """Moves the invoice to PAID only while it is still ISSUED (a conditional update) and,
        only then, writes the event in the same transaction. Returns the stored invoice: the
        given one, or the one a concurrent payment already moved to PAID (no event written)."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self) -> UUID: ...


class PaymentProvider(Protocol):
    def charge(self, invoice: Invoice, idempotency_key: str) -> str:
        """Charges the invoice and returns the provider's reference (1 to 40 characters). The
        provider charges once per key: a retry with the same key returns the first reference.
        Raises PaymentDeclined when the provider refuses it and PaymentProviderUnavailable when
        it does not answer."""


class DependencyProbe(Protocol):
    """A dependency the service needs to take traffic (HU-PLT-004): `ping` returns when it answers
    within the adapter's short timeout and raises otherwise."""

    name: str

    def ping(self) -> None: ...
