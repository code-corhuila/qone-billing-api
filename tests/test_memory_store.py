"""The in-memory store keeps the semantics the PostgreSQL adapter must keep too."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from billing.adapter.outbound.persistence.memory import InMemoryInvoiceStore
from billing.application.port.outbound.ports import DuplicateInvoice
from billing.domain.model.events import invoice_issued
from billing.domain.model.invoice import Invoice

NOW = datetime(2026, 10, 12, tzinfo=UTC)


def an_invoice(student=None, term="2026-B"):
    return Invoice.issue(uuid4(), student or uuid4(), "Laura Gómez", term, 100, NOW)


def test_a_used_key_returns_the_first_invoice_and_keeps_nothing_new():
    store = InMemoryInvoiceStore()
    first, created = store.create(an_invoice(), "key-0001", invoice_issued(an_invoice()))
    other = an_invoice()
    again, created_again = store.create(other, "key-0001", invoice_issued(other))
    assert created and not created_again and again == first
    assert store.find(other.id) is None and len(store.outbox) == 1


def test_the_unique_index_of_inv_bil_001_is_simulated():
    store = InMemoryInvoiceStore()
    student = UUID("11111111-1111-4111-8111-111111111111")
    store.create(an_invoice(student), "key-0001", invoice_issued(an_invoice(student)))
    with pytest.raises(DuplicateInvoice):
        store.create(an_invoice(student), "key-0002", invoice_issued(an_invoice(student)))
