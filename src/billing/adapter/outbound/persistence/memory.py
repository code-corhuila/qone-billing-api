"""In-memory store: the fake of the InvoiceStore port for the core and HTTP tests (Annex C),
with the same semantics the PostgreSQL adapter must keep: one invoice per student and term,
a key used once, events kept next to the change."""

from uuid import UUID

from billing.application.port.outbound.ports import DuplicateInvoice
from billing.domain.model.events import DomainEvent
from billing.domain.model.invoice import Invoice


class InMemoryInvoiceStore:
    def __init__(self, invoices: list[Invoice] | None = None) -> None:
        self._invoices: dict[UUID, Invoice] = {i.id: i for i in invoices or []}
        self._keys: dict[str, UUID] = {}
        self.outbox: list[DomainEvent] = []

    def find_by_key(self, idempotency_key: str) -> Invoice | None:
        invoice_id = self._keys.get(idempotency_key)
        return self._invoices.get(invoice_id) if invoice_id else None

    def exists(self, student_id: UUID, term: str) -> bool:
        return any(i.student_id == student_id and i.term == term for i in self._invoices.values())

    def create(self, invoice: Invoice, idempotency_key: str, event: DomainEvent) -> tuple[Invoice, bool]:
        earlier = self.find_by_key(idempotency_key)
        if earlier is not None:
            return earlier, False
        if self.exists(invoice.student_id, invoice.term):
            raise DuplicateInvoice()
        self._invoices[invoice.id] = invoice
        self._keys[idempotency_key] = invoice.id
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

    def save_paid(self, invoice: Invoice, event: DomainEvent) -> None:
        self._invoices[invoice.id] = invoice
        self.outbox.append(event)
