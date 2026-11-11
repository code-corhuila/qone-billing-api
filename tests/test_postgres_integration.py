"""Integration level (Annex C): the real engine with the schema of qone-billing-db, through
TEST_DATABASE_URL. Skipped, not failed, when the variable is absent. A fake store proves the
use case called it; only the engine proves the SQL, the types and the migration exist."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from billing.application.port.inbound.caller import Caller, Role
from billing.application.port.outbound.ports import DuplicateInvoice, IdempotencyClaim
from billing.domain.model.events import invoice_issued, tuition_paid
from billing.domain.model.invoice import Invoice, InvoiceStatus

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")

NOW = datetime(2026, 10, 12, 15, 0, 0, tzinfo=UTC)
STUDENT = UUID("11111111-1111-4111-8111-111111111119")
PATRICIA, ROCIO = "33333333-3333-4333-8333-333333333331", "33333333-3333-4333-8333-333333333332"


def claim(key: str, owner: str = PATRICIA, body: str = "a") -> IdempotencyClaim:
    return IdempotencyClaim(owner, key, body * 64)


@pytest.fixture(scope="module")
def pool():
    from billing.adapter.outbound.persistence.postgres import connect

    pool = connect(URL, max_size=2)
    yield pool
    pool.close()


@pytest.fixture
def store(pool):
    from billing.adapter.outbound.persistence.postgres import PostgresInvoiceStore

    with pool.connection() as conn:
        conn.execute("TRUNCATE billing.idempotency_key, billing.outbox")
        conn.execute("DELETE FROM billing.invoice WHERE student_id = %s", (STUDENT,))
    return PostgresInvoiceStore(pool)


def new_invoice(term="2026-B", student=STUDENT):
    return Invoice.issue(uuid4(), student, "Nuevo Estudiante", term, 185_000_050, NOW)


def outbox(pool):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT event_type, payload, aggregate_id FROM billing.outbox ORDER BY occurred_at"
        ).fetchall()


def test_round_trip_keeps_every_type(store):
    invoice = new_invoice()
    stored, created = store.create(invoice, claim("key-roundtrip-0001"), invoice_issued(invoice))
    assert created and stored == invoice
    found = store.find(invoice.id)
    assert found == invoice
    assert isinstance(found.amount_cents, int) and found.created_at.tzinfo is not None


def test_the_key_and_the_event_are_written_with_the_invoice_in_one_transaction(store, pool):
    invoice = new_invoice()
    store.create(invoice, claim("key-event-000001"), invoice_issued(invoice))
    rows = outbox(pool)
    assert [r["event_type"] for r in rows] == ["InvoiceIssued"]
    assert rows[0]["payload"]["invoiceId"] == str(invoice.id) and rows[0]["aggregate_id"] == invoice.id
    assert store.find_by_key(PATRICIA, "key-event-000001") == (invoice, "a" * 64)


def test_a_used_key_rolls_back_and_returns_the_first_invoice(store, pool):
    first = new_invoice(term="2026-A")
    store.create(first, claim("key-replay-00001"), invoice_issued(first))
    second = new_invoice(term="2027-A")
    again, created = store.create(second, claim("key-replay-00001"), invoice_issued(second))
    assert created is False and again == first
    assert store.find(second.id) is None, "the second invoice was rolled back"
    assert len(outbox(pool)) == 1


def test_the_key_is_scoped_to_its_owner(store):
    patricias, rocios = new_invoice(term="2026-A"), new_invoice(term="2027-A")
    store.create(patricias, claim("key-owner-00001"), invoice_issued(patricias))
    stored, created = store.create(rocios, claim("key-owner-00001", owner=ROCIO, body="b"), invoice_issued(rocios))
    assert created and stored == rocios
    assert store.find_by_key(ROCIO, "key-owner-00001") == (rocios, "b" * 64)
    assert store.find_by_key(PATRICIA, "key-owner-00001") == (patricias, "a" * 64)
    assert store.find_by_key("qone-workflow", "key-owner-00001") is None


def test_the_unique_index_of_inv_bil_001_is_duplicate_invoice(store):
    store.create(new_invoice(), claim("key-unique-00001"), invoice_issued(new_invoice()))
    with pytest.raises(DuplicateInvoice):
        store.create(new_invoice(), claim("key-unique-00002"), invoice_issued(new_invoice()))


def test_save_paid_updates_the_row_and_writes_tuition_paid(store, pool):
    invoice = new_invoice()
    store.create(invoice, claim("key-pay-0000001"), invoice_issued(invoice))
    paid, _ = invoice.pay("SIM-7F3A9C21", datetime(2026, 10, 13, 9, 30, tzinfo=UTC))
    store.save_paid(paid, tuition_paid(paid))
    found = store.find(invoice.id)
    assert (
        found.status is InvoiceStatus.PAID
        and found.provider_reference == "SIM-7F3A9C21"
        and found.paid_at == paid.paid_at
    )
    assert [r["event_type"] for r in outbox(pool)] == ["InvoiceIssued", "TuitionPaid"]


def test_save_paid_moves_only_an_issued_row_and_a_late_one_gets_the_stored_invoice(store, pool):
    invoice = new_invoice()
    store.create(invoice, claim("key-pay-0000002"), invoice_issued(invoice))
    first, _ = invoice.pay("SIM-00000001", datetime(2026, 10, 13, 9, 30, tzinfo=UTC))
    late, _ = invoice.pay("SIM-00000002", datetime(2026, 10, 13, 9, 31, tzinfo=UTC))
    assert store.save_paid(first, tuition_paid(first)) == first
    assert store.save_paid(late, tuition_paid(late)) == first, "the conditional UPDATE matched no row"
    assert store.find(invoice.id).provider_reference == "SIM-00000001"
    assert [r["event_type"] for r in outbox(pool)] == ["InvoiceIssued", "TuitionPaid"]


def paying_service(store, provider):
    from billing.application.usecase.invoices import InvoiceService
    from tests.fakes import FixedClock, SequenceIds

    return InvoiceService(store, FixedClock(), SequenceIds(), provider, current_term="2026-B")


def test_two_concurrent_payments_of_the_same_invoice_charge_once_and_write_one_tuition_paid(store, pool):
    from billing.adapter.outbound.payment.simulated import SimulatedPaymentProvider

    invoice = new_invoice()
    store.create(invoice, claim("key-race-0000001"), invoice_issued(invoice))
    simulator = SimulatedPaymentProvider()
    both_read_it = threading.Barrier(2, timeout=10)

    class Racing:
        def charge(self, invoice, idempotency_key):
            both_read_it.wait()  # both requests saw the invoice ISSUED before either one charges
            return simulator.charge(invoice, idempotency_key)

    service = paying_service(store, Racing())
    student = Caller(STUDENT, Role.STUDENT, "Nuevo Estudiante", str(STUDENT))
    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(lambda _: service.pay(student, invoice.id), range(2)))
    assert results[0] == results[1] and results[0].status is InvoiceStatus.PAID
    assert len(simulator.charges) == 1, "one charge at the provider"
    paid_events = [r for r in outbox(pool) if r["event_type"] == "TuitionPaid"]
    assert len(paid_events) == 1 and paid_events[0]["payload"]["providerReference"] == results[0].provider_reference


def test_a_retry_after_the_save_failed_charges_once(store, pool):
    import psycopg

    from billing.adapter.outbound.payment.simulated import SimulatedPaymentProvider

    invoice = new_invoice()
    store.create(invoice, claim("key-retry-pay-01"), invoice_issued(invoice))
    simulator, save_paid, calls = SimulatedPaymentProvider(), store.save_paid, []

    def fails_the_first_time(paid, event):
        calls.append(paid)
        if len(calls) == 1:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return save_paid(paid, event)

    store.save_paid = fails_the_first_time
    service = paying_service(store, simulator)
    student = Caller(STUDENT, Role.STUDENT, "Nuevo Estudiante", str(STUDENT))
    with pytest.raises(psycopg.OperationalError):
        service.pay(student, invoice.id)
    assert store.find(invoice.id).status is InvoiceStatus.ISSUED
    paid = service.pay(student, invoice.id)
    assert paid.status is InvoiceStatus.PAID and len(simulator.charges) == 1
    assert paid.provider_reference == simulator.charges[str(invoice.id)]
    assert [r["event_type"] for r in outbox(pool)] == ["InvoiceIssued", "TuitionPaid"]


def test_the_page_is_newest_first_with_the_total_and_the_current_term_is_found(store):
    old = new_invoice(term="2025-B")
    store.create(old, claim("key-page-0000001"), invoice_issued(old))
    new = Invoice.issue(uuid4(), STUDENT, "Nuevo Estudiante", "2026-B", 1, datetime(2026, 11, 1, tzinfo=UTC))
    store.create(new, claim("key-page-0000002"), invoice_issued(new))
    items, total = store.page_of(STUDENT, None, 1, 1)
    assert items == [new] and total == 2
    items, total = store.page_of(STUDENT, "2025-B", 1, 20)
    assert items == [old] and total == 1
    assert store.find_current(STUDENT, "2026-B") == new and store.exists(STUDENT, "2025-B")
    assert store.find_current(STUDENT, "2024-A") is None


def test_the_seed_of_the_database_serves_the_tuition_gate(store):
    """The synthetic invoices of qone-billing-db: Santiago unpaid, Laura paid."""
    santiago = store.find_current(UUID("11111111-1111-4111-8111-111111111112"), "2026-B")
    laura = store.find_current(UUID("11111111-1111-4111-8111-111111111111"), "2026-B")
    assert santiago is not None and santiago.status is InvoiceStatus.ISSUED
    assert laura is not None and laura.status is InvoiceStatus.PAID and laura.provider_reference == "SIM-00000001"


def test_a_retry_of_the_same_key_returns_the_first_invoice_even_against_the_unique_index(store):
    first = new_invoice()
    store.create(first, claim("key-retry-000001"), invoice_issued(first))
    retry = new_invoice()  # same student and term: would trip INV-BIL-001 if the key were claimed last
    again, created = store.create(retry, claim("key-retry-000001"), invoice_issued(retry))
    assert created is False and again == first


def test_the_ready_probe_answers_against_the_real_engine(pool):
    from billing.adapter.outbound.persistence.postgres import PostgresProbe

    PostgresProbe(pool, timeout_seconds=2.0).ping()
