"""The simulated payment provider of Qampus: it returns a reference `SIM-` plus eight upper-case
hexadecimal characters (contract example SIM-7F3A9C21). The real provider is out of scope
(03-product/scope.md).

Declined rule (deterministic, so the declined path can be shown and tested): a charge whose
amount in cents ends in 51 - the cents part of the COP amount is 51, ISO 8583 response code 51
"insufficient funds" - is declined with PaymentDeclined. Every other amount is approved, so the
seed (185 000 000 cents) and the portal's happy path are unchanged."""

import secrets

from billing.application.port.outbound.ports import PaymentDeclined
from billing.domain.model.invoice import Invoice

DECLINED_CENTS = 51


class SimulatedPaymentProvider:
    def charge(self, invoice: Invoice) -> str:
        if invoice.amount_cents % 100 == DECLINED_CENTS:
            raise PaymentDeclined("insufficient funds")
        return f"SIM-{secrets.token_hex(4).upper()}"
