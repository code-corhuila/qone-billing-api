"""The simulated provider (adapter level): it charges once per idempotency key, like a real
provider, so a retry of the same payment - after a database failure, or a second request
racing the first - returns the first reference instead of charging twice."""

import re
from datetime import UTC, datetime
from uuid import uuid4

from billing.adapter.outbound.payment.simulated import SimulatedPaymentProvider
from billing.domain.model.invoice import Invoice

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)


def invoice_of(cents: int = 185_000_000) -> Invoice:
    return Invoice.issue(uuid4(), uuid4(), "Laura Gómez", "2026-B", cents, NOW)


def test_a_charge_is_approved_with_a_sim_reference():
    invoice = invoice_of()
    assert re.fullmatch(r"SIM-[0-9A-F]{8}", SimulatedPaymentProvider().charge(invoice, str(invoice.id)))


def test_the_same_key_charges_once_and_returns_the_first_reference():
    provider, invoice = SimulatedPaymentProvider(), invoice_of()
    first = provider.charge(invoice, str(invoice.id))
    assert provider.charge(invoice, str(invoice.id)) == first
    assert provider.charges == {str(invoice.id): first}


def test_another_key_is_another_charge():
    provider, one, other = SimulatedPaymentProvider(), invoice_of(), invoice_of()
    assert provider.charge(one, str(one.id)) != provider.charge(other, str(other.id))
    assert len(provider.charges) == 2
