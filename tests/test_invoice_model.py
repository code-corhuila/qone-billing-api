"""Core level (Annex C): the Invoice aggregate alone, no server, no database."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from billing.domain.model.errors import ValidationError
from billing.domain.model.events import invoice_issued, tuition_paid
from billing.domain.model.invoice import Invoice, InvoiceStatus

NOW = datetime(2026, 10, 12, 15, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 13, 9, 30, 0, tzinfo=UTC)


def issued(**overrides):
    args = dict(
        invoice_id=uuid4(),
        student_id=uuid4(),
        student_name="Laura Gómez",
        term="2026-B",
        amount_cents=185_000_000,
        now=NOW,
    )
    args.update(overrides)
    return Invoice.issue(**args)


class TestIssue:
    def test_a_new_invoice_is_issued_unpaid_with_the_given_moment(self):
        invoice = issued()
        assert invoice.status is InvoiceStatus.ISSUED
        assert invoice.provider_reference is None and invoice.paid_at is None
        assert invoice.created_at == NOW and invoice.updated_at == NOW
        assert invoice.is_paid is False

    def test_the_name_is_trimmed(self):
        assert issued(student_name="  Laura Gómez  ").student_name == "Laura Gómez"

    def test_a_naive_moment_is_taken_as_utc(self):
        assert issued(now=datetime(2026, 10, 12, 15, 0, 0)).created_at == NOW

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"student_name": "L"}, "studentName"),
            ({"student_name": "x" * 121}, "studentName"),
            ({"term": "2026-C"}, "term"),
            ({"term": "26-B"}, "term"),
            ({"amount_cents": 0}, "amountCents"),
            ({"amount_cents": -1}, "amountCents"),
            ({"amount_cents": 1850000.5}, "amountCents"),
            ({"amount_cents": True}, "amountCents"),
        ],
    )
    def test_an_invalid_field_is_named_in_the_error(self, overrides, field):
        with pytest.raises(ValidationError) as caught:
            issued(**overrides)
        assert [d.field for d in caught.value.details] == [field]

    def test_every_invalid_field_is_reported_at_once(self):
        with pytest.raises(ValidationError) as caught:
            issued(student_name="", term="bad", amount_cents=0)
        assert [d.field for d in caught.value.details] == ["studentName", "term", "amountCents"]


class TestPay:
    def test_paying_moves_issued_to_paid_exactly_once(self):
        invoice = issued()
        paid, changed = invoice.pay("SIM-00000101", LATER)
        assert changed is True
        assert paid.status is InvoiceStatus.PAID
        assert paid.provider_reference == "SIM-00000101"
        assert paid.paid_at == LATER and paid.updated_at == LATER
        assert paid.created_at == NOW
        assert invoice.status is InvoiceStatus.ISSUED, "the aggregate is a value; the original is untouched"

    def test_paying_a_paid_invoice_returns_it_unchanged(self):
        paid, _ = issued().pay("SIM-00000101", LATER)
        again, changed = paid.pay("SIM-99999999", datetime(2026, 12, 1, tzinfo=UTC))
        assert changed is False
        assert again == paid, "INV-BIL-002: PAID is terminal; the first payment stays (D-04)"

    @pytest.mark.parametrize("reference", ["", "x" * 41])
    def test_the_provider_reference_has_one_to_forty_characters(self, reference):
        with pytest.raises(ValueError):
            issued().pay(reference, LATER)


class TestEvents:
    def test_invoice_issued_carries_the_api_shape_in_camel_case(self):
        invoice = issued()
        event = invoice_issued(invoice)
        assert event.event_type == "InvoiceIssued"
        assert event.aggregate_type == "invoice" and event.aggregate_id == invoice.id
        assert event.payload == {
            "invoiceId": str(invoice.id),
            "studentId": str(invoice.student_id),
            "studentName": "Laura Gómez",
            "term": "2026-B",
            "amountCents": 185_000_000,
            "issuedAt": "2026-10-12T15:00:00Z",
        }
        assert event.occurred_at == NOW

    def test_tuition_paid_carries_the_reference_and_the_moment(self):
        paid, _ = issued().pay("SIM-00000101", LATER)
        event = tuition_paid(paid)
        assert event.event_type == "TuitionPaid"
        assert event.payload["providerReference"] == "SIM-00000101"
        assert event.payload["paidAt"] == "2026-10-13T09:30:00Z"
        assert event.occurred_at == LATER
