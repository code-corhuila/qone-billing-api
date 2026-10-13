"""Integration level (Annex C): the real engine with the schema of qone-billing-db, through
TEST_DATABASE_URL. Skipped, not failed, when the variable is absent. A fake store proves the
use case called it; only the engine proves the SQL, the types and the migration exist."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from billing.application.port.outbound.ports import DuplicateInvoice
from billing.domain.model.events import invoice_issued, tuition_paid
from billing.domain.model.invoice import Invoice, InvoiceStatus

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")

NOW = datetime(2026, 10, 12, 15, 0, 0, tzinfo=UTC)
STUDENT = UUID("11111111-1111-4111-8111-111111111119")


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
    stored, created = store.create(invoice, "key-roundtrip-0001", invoice_issued(invoice))
    assert created and stored == invoice
    found = store.find(invoice.id)
    assert found == invoice
    assert isinstance(found.amount_cents, int) and found.created_at.tzinfo is not None


def test_the_key_and_the_event_are_written_with_the_invoice_in_one_transaction(store, pool):
    invoice = new_invoice()
    store.create(invoice, "key-event-000001", invoice_issued(invoice))
    rows = outbox(pool)
    assert [r["event_type"] for r in rows] == ["InvoiceIssued"]
    assert rows[0]["payload"]["invoiceId"] == str(invoice.id) and rows[0]["aggregate_id"] == invoice.id
    assert store.find_by_key("key-event-000001") == invoice


def test_a_used_key_rolls_back_and_returns_the_first_invoice(store, pool):
    first = new_invoice(term="2026-A")
    store.create(first, "key-replay-00001", invoice_issued(first))
    second = new_invoice(term="2027-A")
    again, created = store.create(second, "key-replay-00001", invoice_issued(second))
    assert created is False and again == first
    assert store.find(second.id) is None, "the second invoice was rolled back"
    assert len(outbox(pool)) == 1


def test_the_unique_index_of_inv_bil_001_is_duplicate_invoice(store):
    store.create(new_invoice(), "key-unique-00001", invoice_issued(new_invoice()))
    with pytest.raises(DuplicateInvoice):
        store.create(new_invoice(), "key-unique-00002", invoice_issued(new_invoice()))


def test_save_paid_updates_the_row_and_writes_tuition_paid(store, pool):
    invoice = new_invoice()
    store.create(invoice, "key-pay-0000001", invoice_issued(invoice))
    paid, _ = invoice.pay("SIM-7F3A9C21", datetime(2026, 10, 13, 9, 30, tzinfo=UTC))
    store.save_paid(paid, tuition_paid(paid))
    found = store.find(invoice.id)
    assert (
        found.status is InvoiceStatus.PAID
        and found.provider_reference == "SIM-7F3A9C21"
        and found.paid_at == paid.paid_at
    )
    assert [r["event_type"] for r in outbox(pool)] == ["InvoiceIssued", "TuitionPaid"]


def test_the_page_is_newest_first_with_the_total_and_the_current_term_is_found(store):
    old = new_invoice(term="2025-B")
    store.create(old, "key-page-0000001", invoice_issued(old))
    new = Invoice.issue(uuid4(), STUDENT, "Nuevo Estudiante", "2026-B", 1, datetime(2026, 11, 1, tzinfo=UTC))
    store.create(new, "key-page-0000002", invoice_issued(new))
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
    store.create(first, "key-retry-000001", invoice_issued(first))
    retry = new_invoice()  # same student and term: would trip INV-BIL-001 if the key were claimed last
    again, created = store.create(retry, "key-retry-000001", invoice_issued(retry))
    assert created is False and again == first
