"""Fakes of the trivial outbound ports for the core and HTTP tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from billing.domain.model.invoice import Invoice


class FixedClock:
    def __init__(self, start: datetime = datetime(2026, 10, 12, 15, 0, 0, tzinfo=UTC)) -> None:
        self.current = start

    def now(self) -> datetime:
        return self.current

    def tick(self, **delta) -> datetime:
        self.current = self.current + timedelta(**delta)
        return self.current


class SequenceIds:
    """Predictable ids: 88888888-...-8888888888NN, counting from the given start."""

    def __init__(self, start: int = 1) -> None:
        self.next = start

    def new_id(self) -> UUID:
        value = UUID(f"88888888-8888-4888-8888-8888888888{self.next:02d}")
        self.next += 1
        return value


class FakeProvider:
    """Charges once per idempotency key, like a real provider: a retry with the same key returns
    the first reference. `charges` keeps the invoices actually charged, `keys` every key received."""

    def __init__(self) -> None:
        self.charges: list[Invoice] = []
        self.keys: list[str] = []
        self._references: dict[str, str] = {}

    def charge(self, invoice: Invoice, idempotency_key: str) -> str:
        self.keys.append(idempotency_key)
        if idempotency_key not in self._references:
            self.charges.append(invoice)
            self._references[idempotency_key] = f"SIM-{len(self.charges):08d}"
        return self._references[idempotency_key]
