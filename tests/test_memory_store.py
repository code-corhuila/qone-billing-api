"""The in-memory store keeps the semantics the PostgreSQL adapter must keep too."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from billing.adapter.outbound.persistence.memory import InMemoryInvoiceStore
from billing.application.port.outbound.ports import DuplicateInvoice, IdempotencyClaim
from billing.domain.model.events import invoice_issued, tuition_paid
from billing.domain.model.invoice import Invoice

NOW = datetime(2026, 10, 12, tzinfo=UTC)
PATRICIA, ROCIO = "33333333-3333-4333-8333-333333333331", "33333333-3333-4333-8333-333333333332"


def claim(key: str, owner: str = PATRICIA, body: str = "a") -> IdempotencyClaim:
    return IdempotencyClaim(owner, key, body * 64)


def an_invoice(student=None, term="2026-B"):
    return Invoice.issue(uuid4(), student or uuid4(), "Laura Gómez", term, 100, NOW)


def test_a_used_key_returns_the_first_invoice_and_keeps_nothing_new():
    store = InMemoryInvoiceStore()
    first, created = store.create(an_invoice(), claim("key-0001"), invoice_issued(an_invoice()))
    other = an_invoice()
    again, created_again = store.create(other, claim("key-0001"), invoice_issued(other))
    assert created and not created_again and again == first
    assert store.find(other.id) is None and len(store.outbox) == 1
    assert store.find_by_key(PATRICIA, "key-0001") == (first, "a" * 64)


def test_the_same_key_of_another_owner_is_another_key():
    store = InMemoryInvoiceStore()
    patricias, rocios = an_invoice(), an_invoice()
    store.create(patricias, claim("key-0001"), invoice_issued(patricias))
    stored, created = store.create(rocios, claim("key-0001", owner=ROCIO, body="b"), invoice_issued(rocios))
    assert created and stored == rocios
    assert store.find_by_key(ROCIO, "key-0001") == (rocios, "b" * 64)
    assert store.find_by_key(PATRICIA, "key-0001") == (patricias, "a" * 64)
    assert store.find_by_key("someone-else", "key-0001") is None


def test_save_paid_moves_only_an_issued_invoice_and_returns_the_stored_one():
    store = InMemoryInvoiceStore()
    invoice = an_invoice()
    store.create(invoice, claim("key-0001"), invoice_issued(invoice))
    first, _ = invoice.pay("SIM-00000001", NOW)
    assert store.save_paid(first, tuition_paid(first)) == first
    late, _ = invoice.pay("SIM-00000002", NOW)
    assert store.save_paid(late, tuition_paid(late)) == first
    assert [e.event_type for e in store.outbox] == ["InvoiceIssued", "TuitionPaid"]


def test_the_unique_index_of_inv_bil_001_is_simulated():
    store = InMemoryInvoiceStore()
    student = UUID("11111111-1111-4111-8111-111111111111")
    store.create(an_invoice(student), claim("key-0001"), invoice_issued(an_invoice(student)))
    with pytest.raises(DuplicateInvoice):
        store.create(an_invoice(student), claim("key-0002"), invoice_issued(an_invoice(student)))
