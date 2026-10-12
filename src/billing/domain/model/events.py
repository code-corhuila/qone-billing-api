"""Events the billing domain publishes (02-domain/domain-events.md): InvoiceIssued and
TuitionPaid. They are written to the outbox in the transaction of the change (norm 5.3.11);
the payload is camelCase, the shape the API returns, so a consumer and a client read the same
names."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    occurred_at: datetime


def _rfc3339(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def invoice_issued(invoice: "Invoice") -> DomainEvent:  # noqa: F821 - forward reference, imported lazily
    return DomainEvent(
        event_type="InvoiceIssued",
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "invoiceId": str(invoice.id),
            "studentId": str(invoice.student_id),
            "studentName": invoice.student_name,
            "term": invoice.term,
            "amountCents": invoice.amount_cents,
            "issuedAt": _rfc3339(invoice.created_at),
        },
        occurred_at=invoice.created_at,
    )


def tuition_paid(invoice: "Invoice") -> DomainEvent:  # noqa: F821
    assert invoice.paid_at is not None and invoice.provider_reference is not None
    return DomainEvent(
        event_type="TuitionPaid",
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "invoiceId": str(invoice.id),
            "studentId": str(invoice.student_id),
            "term": invoice.term,
            "amountCents": invoice.amount_cents,
            "providerReference": invoice.provider_reference,
            "paidAt": _rfc3339(invoice.paid_at),
        },
        occurred_at=invoice.paid_at,
    )
