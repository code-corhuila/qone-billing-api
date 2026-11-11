"""The simulated payment provider of Qampus: it approves every charge and returns a reference
`SIM-` plus eight upper-case hexadecimal characters (contract example SIM-7F3A9C21). The real
provider is out of scope (03-product/scope.md).

Like a real provider, it charges once per idempotency key: a retry with the same key returns
the first reference without charging again. The keys live in this process (one per invoice
paid); the database still decides, with its conditional update, which request writes
TuitionPaid."""

import secrets
import threading

from billing.domain.model.invoice import Invoice


class SimulatedPaymentProvider:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.charges: dict[str, str] = {}
        """The charges made, reference by idempotency key."""

    def charge(self, invoice: Invoice, idempotency_key: str) -> str:
        with self._lock:
            reference = self.charges.get(idempotency_key)
            if reference is None:
                reference = self.charges[idempotency_key] = f"SIM-{secrets.token_hex(4).upper()}"
            return reference
