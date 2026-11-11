"""The simulated provider (adapter level): it approves every charge except the documented
declined rule, an amount whose cents part is 51 (ISO 8583 response code 51, insufficient
funds), so the declined path can be shown end to end without a real provider."""

import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from billing.adapter.outbound.payment.simulated import DECLINED_CENTS, SimulatedPaymentProvider
from billing.application.port.outbound.ports import PaymentDeclined
from billing.domain.model.invoice import Invoice

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)


def invoice_of(cents: int) -> Invoice:
    return Invoice.issue(uuid4(), uuid4(), "Laura Gómez", "2026-B", cents, NOW)


@pytest.mark.parametrize("cents", [185_000_000, 185_000_050, 1, 185_000_052])
def test_any_other_amount_is_approved_with_a_sim_reference(cents):
    reference = SimulatedPaymentProvider().charge(invoice_of(cents))
    assert re.fullmatch(r"SIM-[0-9A-F]{8}", reference)


@pytest.mark.parametrize("cents", [185_000_051, 51, 151])
def test_an_amount_whose_cents_part_is_51_is_declined(cents):
    assert DECLINED_CENTS == 51
    with pytest.raises(PaymentDeclined) as caught:
        SimulatedPaymentProvider().charge(invoice_of(cents))
    assert caught.value.reason == "insufficient funds"
