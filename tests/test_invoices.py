"""Core level (Annex C): the use cases over the in-memory store and fakes of the ports.
Authorization by role and ownership, idempotent creation by key, INV-BIL-001, pay exactly
once, bounded listing. No server, no database."""

from uuid import UUID, uuid4

import pytest

from billing.adapter.outbound.persistence.memory import InMemoryInvoiceStore
from billing.application.errors import Forbidden, NotFound
from billing.application.port.inbound.caller import Caller, Role
from billing.application.port.inbound.invoices import IssueInvoice
from billing.application.usecase.invoices import InvoiceService
from billing.domain.model.errors import BusinessRuleViolation, ValidationError
from billing.domain.model.invoice import InvoiceStatus
from tests.fakes import FakeProvider, FixedClock, SequenceIds

LAURA = UUID("11111111-1111-4111-8111-111111111111")
SANTIAGO = UUID("11111111-1111-4111-8111-111111111112")
PATRICIA = UUID("33333333-3333-4333-8333-333333333331")
CARLOS = UUID("22222222-2222-4222-8222-222222222221")
WORKFLOW = UUID("44444444-4444-4444-8444-444444444441")

admin = Caller(PATRICIA, Role.ADMIN, "Patricia Mora")
laura = Caller(LAURA, Role.STUDENT, "Laura Gómez")
santiago = Caller(SANTIAGO, Role.STUDENT, "Santiago Rojas")
professor = Caller(CARLOS, Role.PROFESSOR, "Carlos Ramírez")
service = Caller(WORKFLOW, Role.SERVICE, "qone-workflow")

KEY = "invoice-6f1d2c3e-9b7a-4e1f-8c2d-0a1b2c3d4e5f"


@pytest.fixture
def world():
    store = InMemoryInvoiceStore()
    clock = FixedClock()
    provider = FakeProvider()
    service_ = InvoiceService(store, clock, SequenceIds(), provider, current_term="2026-B")
    return store, clock, provider, service_


def issue(service_, student=LAURA, name="Laura Gómez", term="2026-B", cents=185_000_000, key=KEY, caller=admin):
    return service_.issue(caller, IssueInvoice(student, name, term, cents), key)


class TestIssue:
    def test_an_admin_issues_an_invoice_and_its_event_is_in_the_outbox(self, world):
        store, clock, _, service_ = world
        result = issue(service_)
        assert result.created is True
        assert result.invoice.id == UUID("88888888-8888-4888-8888-888888888801")
        assert result.invoice.status is InvoiceStatus.ISSUED and result.invoice.created_at == clock.now()
        assert [e.event_type for e in store.outbox] == ["InvoiceIssued"]
        assert store.find(result.invoice.id) == result.invoice

    def test_the_same_key_returns_the_first_invoice_and_creates_nothing(self, world):
        store, _, _, service_ = world
        first = issue(service_)
        again = issue(service_, name="Other Name", cents=1)
        assert again.created is False and again.invoice == first.invoice
        assert len(store.outbox) == 1

    def test_a_second_invoice_for_the_same_student_and_term_breaks_inv_bil_001(self, world):
        _, _, _, service_ = world
        issue(service_)
        with pytest.raises(BusinessRuleViolation) as caught:
            issue(service_, key="invoice-another-intention")
        assert str(caught.value).startswith("INV-BIL-001: Laura Gómez already has an invoice for 2026-B")

    def test_a_new_term_for_the_same_student_is_allowed(self, world):
        _, _, _, service_ = world
        issue(service_)
        assert issue(service_, term="2027-A", key="invoice-next-term-0001").created is True

    @pytest.mark.parametrize("key", ["", "short", "k" * 129])
    def test_the_idempotency_key_has_8_to_128_characters(self, world, key):
        _, _, _, service_ = world
        with pytest.raises(ValidationError) as caught:
            issue(service_, key=key)
        assert caught.value.details[0].field == "Idempotency-Key"

    def test_invalid_fields_come_from_the_aggregate(self, world):
        _, _, _, service_ = world
        with pytest.raises(ValidationError) as caught:
            issue(service_, name="L", cents=0)
        assert [d.field for d in caught.value.details] == ["studentName", "amountCents"]

    @pytest.mark.parametrize("caller", [laura, professor, service])
    def test_only_an_admin_issues(self, world, caller):
        _, _, _, service_ = world
        with pytest.raises(Forbidden):
            issue(service_, caller=caller)


class TestPay:
    def test_the_owner_pays_once_and_the_event_is_in_the_outbox(self, world):
        store, clock, provider, service_ = world
        invoice = issue(service_).invoice
        paid_at = clock.tick(days=1)
        paid = service_.pay(laura, invoice.id)
        assert paid.status is InvoiceStatus.PAID
        assert paid.provider_reference == "SIM-00000001" and paid.paid_at == paid_at
        assert [e.event_type for e in store.outbox] == ["InvoiceIssued", "TuitionPaid"]
        assert store.find(invoice.id) == paid

    def test_paying_again_returns_the_same_invoice_without_a_second_charge(self, world):
        store, _, provider, service_ = world
        invoice = issue(service_).invoice
        first = service_.pay(laura, invoice.id)
        second = service_.pay(laura, invoice.id)
        assert second == first
        assert len(provider.charges) == 1 and len(store.outbox) == 2

    def test_another_students_invoice_does_not_exist_for_the_payer(self, world):
        _, _, _, service_ = world
        invoice = issue(service_).invoice
        with pytest.raises(NotFound):
            service_.pay(santiago, invoice.id)

    @pytest.mark.parametrize("caller", [admin, professor, service])
    def test_only_a_student_pays(self, world, caller):
        _, _, _, service_ = world
        invoice = issue(service_).invoice
        with pytest.raises(Forbidden):
            service_.pay(caller, invoice.id)

    def test_an_unknown_invoice_is_not_found(self, world):
        _, _, _, service_ = world
        with pytest.raises(NotFound):
            service_.pay(laura, uuid4())


class TestGet:
    def test_the_owner_an_admin_and_a_service_read_it(self, world):
        _, _, _, service_ = world
        invoice = issue(service_).invoice
        for caller in (laura, admin, service):
            assert service_.get(caller, invoice.id) == invoice

    def test_another_student_gets_not_found_and_a_professor_is_forbidden(self, world):
        _, _, _, service_ = world
        invoice = issue(service_).invoice
        with pytest.raises(NotFound):
            service_.get(santiago, invoice.id)
        with pytest.raises(Forbidden):
            service_.get(professor, invoice.id)


class TestMyInvoices:
    def test_newest_first_with_the_page_meta(self, world):
        _, clock, _, service_ = world
        old = issue(service_, term="2025-B", key="invoice-2025-b-00001").invoice
        clock.tick(days=90)
        new = issue(service_, term="2026-A", key="invoice-2026-a-00001").invoice
        page = service_.my_invoices(laura, term=None, page=1, limit=20)
        assert page.items == [new, old]
        assert (page.page, page.limit, page.total, page.total_pages) == (1, 20, 2, 1)

    def test_the_term_filter_and_a_second_page(self, world):
        _, clock, _, service_ = world
        issue(service_, term="2025-B", key="invoice-2025-b-00001")
        clock.tick(days=90)
        issue(service_, term="2026-A", key="invoice-2026-a-00001")
        assert [i.term for i in service_.my_invoices(laura, "2025-B", 1, 20).items] == ["2025-B"]
        second = service_.my_invoices(laura, None, 2, 1)
        assert [i.term for i in second.items] == ["2025-B"] and second.total_pages == 2

    def test_a_student_without_invoices_gets_an_empty_page(self, world):
        _, _, _, service_ = world
        page = service_.my_invoices(santiago, None, 1, 20)
        assert page.items == [] and page.total == 0 and page.total_pages == 0

    @pytest.mark.parametrize(
        ("page", "limit", "term", "field"),
        [(0, 20, None, "page"), (1, 0, None, "limit"), (1, 101, None, "limit"), (1, 20, "2026", "term")],
    )
    def test_bounds_are_validated_with_the_contract_field_names(self, world, page, limit, term, field):
        _, _, _, service_ = world
        with pytest.raises(ValidationError) as caught:
            service_.my_invoices(laura, term, page, limit)
        assert [d.field for d in caught.value.details] == [field]

    @pytest.mark.parametrize("caller", [admin, professor, service])
    def test_only_a_student_has_my_invoices(self, world, caller):
        _, _, _, service_ = world
        with pytest.raises(Forbidden):
            service_.my_invoices(caller, None, 1, 20)


class TestCurrentOf:
    def test_an_admin_or_a_service_reads_the_current_term_invoice(self, world):
        _, _, _, service_ = world
        issue(service_, term="2025-B", key="invoice-2025-b-00001")
        current = issue(service_, term="2026-B", key="invoice-2026-b-00001").invoice
        assert service_.current_of(admin, LAURA) == current
        assert service_.current_of(service, LAURA) == current

    def test_no_invoice_for_the_current_term_is_not_found(self, world):
        _, _, _, service_ = world
        issue(service_, term="2025-B", key="invoice-2025-b-00001")
        with pytest.raises(NotFound):
            service_.current_of(service, LAURA)

    @pytest.mark.parametrize("caller", [laura, professor])
    def test_a_student_or_a_professor_may_not_ask(self, world, caller):
        _, _, _, service_ = world
        with pytest.raises(Forbidden):
            service_.current_of(caller, LAURA)
