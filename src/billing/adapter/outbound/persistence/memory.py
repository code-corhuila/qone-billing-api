"""In-memory store: the fake of the InvoiceStore port for the core and HTTP tests (Annex C),
with the same semantics the PostgreSQL adapter must keep: one invoice per student and term,
a key used once, events kept next to the change."""

import threading
from uuid import UUID

from billing.application.port.outbound.ports import DuplicateInvoice, IdempotencyClaim
from billing.domain.model.events import DomainEvent
from billing.domain.model.invoice import Invoice


class InMemoryInvoiceStore:
    def __init__(self, invoices: list[Invoice] | None = None) -> None:
        self._invoices: dict[UUID, Invoice] = {i.id: i for i in invoices or []}
        self._keys: dict[tuple[str, str], tuple[UUID, str]] = {}  # (owner, key) -> (invoice id, request hash)
        self.outbox: list[DomainEvent] = []
        self._lock = threading.Lock()

    def find_by_key(self, owner: str, idempotency_key: str) -> tuple[Invoice, str] | None:
        recorded = self._keys.get((owner, idempotency_key))
        if recorded is None:
            return None
        invoice_id, request_hash = recorded
        return self._invoices[invoice_id], request_hash

    def exists(self, student_id: UUID, term: str) -> bool:
        return any(i.student_id == student_id and i.term == term for i in self._invoices.values())

    def create(self, invoice: Invoice, claim: IdempotencyClaim, event: DomainEvent) -> tuple[Invoice, bool]:
        earlier = self.find_by_key(claim.owner, claim.key)
        if earlier is not None:
            return earlier[0], False
        if self.exists(invoice.student_id, invoice.term):
            raise DuplicateInvoice()
        self._invoices[invoice.id] = invoice
        self._keys[(claim.owner, claim.key)] = (invoice.id, claim.request_hash)
        self.outbox.append(event)
        return invoice, True

    def find(self, invoice_id: UUID) -> Invoice | None:
        return self._invoices.get(invoice_id)

    def find_current(self, student_id: UUID, term: str) -> Invoice | None:
        return next((i for i in self._invoices.values() if i.student_id == student_id and i.term == term), None)

    def page_of(self, student_id: UUID, term: str | None, page: int, limit: int) -> tuple[list[Invoice], int]:
        rows = [i for i in self._invoices.values() if i.student_id == student_id and (term is None or i.term == term)]
        rows.sort(key=lambda i: (i.created_at, str(i.id)), reverse=True)
        start = (page - 1) * limit
        return rows[start : start + limit], len(rows)

    def save_paid(self, invoice: Invoice, event: DomainEvent) -> Invoice:
        with self._lock:  # the conditional update of the PostgreSQL adapter
            stored = self._invoices[invoice.id]
            if stored.is_paid:
                return stored
            self._invoices[invoice.id] = invoice
            self.outbox.append(event)
            return invoice


class InMemoryProbe:
    """The ready probe of a service without a database: the in-memory store is always there."""

    name = "database"

    def ping(self) -> None:
        return None
