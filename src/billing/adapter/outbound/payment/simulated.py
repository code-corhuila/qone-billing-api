"""The simulated payment provider of Qampus: it returns a reference `SIM-` plus eight upper-case
hexadecimal characters (contract example SIM-7F3A9C21). The real provider is out of scope
(03-product/scope.md).

Declined rule (deterministic, so the declined path can be shown and tested): a charge whose
amount in cents ends in 51 - the cents part of the COP amount is 51, ISO 8583 response code 51
"insufficient funds" - is declined with PaymentDeclined. Every other amount is approved, so the
seed (185 000 000 cents) and the portal's happy path are unchanged.

Like a real provider, it charges once per idempotency key: a retry with the same key returns
the first reference without charging again. The keys live in this process (one per invoice
paid); the database still decides, with its conditional update, which request writes
TuitionPaid."""

import secrets
import threading

from billing.application.port.outbound.ports import PaymentDeclined
from billing.domain.model.invoice import Invoice

DECLINED_CENTS = 51


class SimulatedPaymentProvider:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.charges: dict[str, str] = {}
        """The charges made, reference by idempotency key."""

    def charge(self, invoice: Invoice, idempotency_key: str) -> str:
        if invoice.amount_cents % 100 == DECLINED_CENTS:
            raise PaymentDeclined("insufficient funds")
        with self._lock:
            reference = self.charges.get(idempotency_key)
            if reference is None:
                reference = self.charges[idempotency_key] = f"SIM-{secrets.token_hex(4).upper()}"
            return reference
