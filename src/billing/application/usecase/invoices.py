"""The operations of the billing service (BI-02..BI-06) over the ports. Authorization by role
and ownership happens here (07-api/authentication.md access matrix); input bounds (page, limit,
term, Idempotency-Key) are checked here with the same field names the contract uses, so the
HTTP adapter only translates."""

from uuid import UUID

from billing.application.errors import Forbidden, NotFound
from billing.application.port.inbound.caller import Caller, Role
from billing.application.port.inbound.invoices import MAX_LIMIT, InvoiceUseCases, Issued, IssueInvoice, Page
from billing.application.port.outbound.ports import Clock, DuplicateInvoice, IdGenerator, InvoiceStore, PaymentProvider
from billing.domain.model.errors import BusinessRuleViolation, FieldError, ValidationError
from billing.domain.model.events import invoice_issued, tuition_paid
from billing.domain.model.invoice import TERM_PATTERN, Invoice

KEY_MIN, KEY_MAX = 8, 128


class InvoiceService(InvoiceUseCases):
    def __init__(
        self,
        store: InvoiceStore,
        clock: Clock,
        ids: IdGenerator,
        payments: PaymentProvider,
        current_term: str,
    ) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids
        self._payments = payments
        self._current_term = current_term

    def issue(self, caller: Caller, command: IssueInvoice, idempotency_key: str) -> Issued:
        _require(caller, Role.ADMIN)
        if not KEY_MIN <= len(idempotency_key or "") <= KEY_MAX:
            raise ValidationError([FieldError("Idempotency-Key", "header required, 8 to 128 characters")])
        earlier = self._store.find_by_key(idempotency_key)
        if earlier is not None:
            return Issued(earlier, created=False)
        invoice = Invoice.issue(
            invoice_id=self._ids.new_id(),
            student_id=command.student_id,
            student_name=command.student_name,
            term=command.term,
            amount_cents=command.amount_cents,
            now=self._clock.now(),
        )
        if self._store.exists(invoice.student_id, invoice.term):
            raise _already_invoiced(invoice)
        try:
            stored, created = self._store.create(invoice, idempotency_key, invoice_issued(invoice))
        except DuplicateInvoice:
            raise _already_invoiced(invoice) from None
        return Issued(stored, created)

    def my_invoices(self, caller: Caller, term: str | None, page: int, limit: int) -> Page:
        _require(caller, Role.STUDENT)
        details: list[FieldError] = []
        if not isinstance(page, int) or page < 1:
            details.append(FieldError("page", "must be 1 or greater"))
        if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            details.append(FieldError("limit", f"must be between 1 and {MAX_LIMIT}"))
        if term is not None and not TERM_PATTERN.match(term):
            details.append(FieldError("term", "must match ^[0-9]{4}-[AB]$"))
        if details:
            raise ValidationError(details)
        items, total = self._store.page_of(caller.user_id, term, page, limit)
        return Page(items=items, page=page, limit=limit, total=total)

    def get(self, caller: Caller, invoice_id: UUID) -> Invoice:
        _require(caller, Role.STUDENT, Role.ADMIN, Role.SERVICE)
        return self._visible(caller, invoice_id)

    def pay(self, caller: Caller, invoice_id: UUID) -> Invoice:
        _require(caller, Role.STUDENT)
        invoice = self._visible(caller, invoice_id)
        if invoice.is_paid:
            return invoice  # INV-BIL-002, D-04: the same invoice, no second charge
        reference = self._payments.charge(invoice)
        paid, changed = invoice.pay(reference, self._clock.now())
        if changed:
            self._store.save_paid(paid, tuition_paid(paid))
        return paid

    def current_of(self, caller: Caller, student_id: UUID) -> Invoice:
        _require(caller, Role.ADMIN, Role.SERVICE)
        invoice = self._store.find_current(student_id, self._current_term)
        if invoice is None:
            raise NotFound()
        return invoice

    def _visible(self, caller: Caller, invoice_id: UUID) -> Invoice:
        invoice = self._store.find(invoice_id)
        if invoice is None or (caller.role is Role.STUDENT and invoice.student_id != caller.user_id):
            raise NotFound()  # D-03: another student's invoice does not exist for this caller
        return invoice


def _require(caller: Caller, *roles: Role) -> None:
    if caller.role not in roles:
        raise Forbidden()


def _already_invoiced(invoice: Invoice) -> BusinessRuleViolation:
    return BusinessRuleViolation(f"INV-BIL-001: {invoice.student_name} already has an invoice for {invoice.term}")
