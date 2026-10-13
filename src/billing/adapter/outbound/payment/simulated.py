"""The simulated payment provider of Qampus v2: it approves every charge and returns a
reference `SIM-` plus eight upper-case hexadecimal characters (contract example SIM-7F3A9C21).
The real provider is out of scope (03-product/scope.md)."""

import secrets

from billing.domain.model.invoice import Invoice


class SimulatedPaymentProvider:
    def charge(self, invoice: Invoice) -> str:
        return f"SIM-{secrets.token_hex(4).upper()}"
