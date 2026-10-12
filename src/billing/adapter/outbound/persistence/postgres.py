"""The InvoiceStore over PostgreSQL (schema `billing` of qone-billing-db) with psycopg 3 and a
connection pool (Annex C limits: pool size, wait for a connection, statement timeout).

Idempotent creation (norm 5.3.8, Annex A): the invoice, its key and its event go in ONE
transaction; the key is inserted with ON CONFLICT DO NOTHING and, when it already existed, the
transaction is rolled back and the invoice the key created first is returned. The unique
index of INV-BIL-001 surfaces as DuplicateInvoice. Every change writes its event to the
outbox in the same transaction (norm 5.3.11)."""

from datetime import UTC
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from billing.application.port.outbound.ports import DuplicateInvoice
from billing.domain.model.events import DomainEvent
from billing.domain.model.invoice import Invoice, InvoiceStatus

COLUMNS = (
    "id, student_id, student_name, term, amount_cents, status, provider_reference, paid_at, created_at, updated_at"
)


def connect(
    url: str, max_size: int = 10, wait_seconds: float = 5.0, statement_timeout_ms: int = 5000
) -> ConnectionPool:
    """A pool with the explicit limits of norm 5.3.10; opening a connection per request would
    exhaust the engine under load."""
    return ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=max_size,
        timeout=wait_seconds,
        kwargs={"options": f"-c statement_timeout={statement_timeout_ms}", "row_factory": dict_row},
        open=True,
    )


class _KeyAlreadyUsed(Exception):
    """Raised inside the transaction to roll it back when the Idempotency-Key existed."""


class PostgresInvoiceStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def find_by_key(self, idempotency_key: str) -> Invoice | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT {COLUMNS} FROM billing.invoice WHERE id = "
                "(SELECT resource_id FROM billing.idempotency_key WHERE key = %s)",
                (idempotency_key,),
            ).fetchone()
        return _invoice(row) if row else None

    def exists(self, student_id: UUID, term: str) -> bool:
        with self._pool.connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM billing.invoice WHERE student_id = %s AND term = %s", (student_id, term)
                ).fetchone()
                is not None
            )

    def create(self, invoice: Invoice, idempotency_key: str, event: DomainEvent) -> tuple[Invoice, bool]:
        try:
            with self._pool.connection() as conn, conn.transaction():
                try:
                    conn.execute(
                        f"INSERT INTO billing.invoice ({COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        _values(invoice),
                    )
                except psycopg.errors.UniqueViolation as cause:
                    raise DuplicateInvoice() from cause
                taken = conn.execute(
                    "INSERT INTO billing.idempotency_key (key, resource_type, resource_id) VALUES (%s, 'invoice', %s) "
                    "ON CONFLICT (key) DO NOTHING RETURNING key",
                    (idempotency_key, invoice.id),
                ).fetchone()
                if taken is None:
                    raise _KeyAlreadyUsed()
                _write_event(conn, event)
        except _KeyAlreadyUsed:
            earlier = self.find_by_key(idempotency_key)
            assert earlier is not None
            return earlier, False
        return invoice, True

    def find(self, invoice_id: UUID) -> Invoice | None:
        with self._pool.connection() as conn:
            row = conn.execute(f"SELECT {COLUMNS} FROM billing.invoice WHERE id = %s", (invoice_id,)).fetchone()
        return _invoice(row) if row else None

    def find_current(self, student_id: UUID, term: str) -> Invoice | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT {COLUMNS} FROM billing.invoice WHERE student_id = %s AND term = %s", (student_id, term)
            ).fetchone()
        return _invoice(row) if row else None

    def page_of(self, student_id: UUID, term: str | None, page: int, limit: int) -> tuple[list[Invoice], int]:
        where = "student_id = %s" + (" AND term = %s" if term else "")
        params: tuple = (student_id, term) if term else (student_id,)
        with self._pool.connection() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM billing.invoice WHERE {where}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT {COLUMNS} FROM billing.invoice WHERE {where} "
                "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                (*params, limit, (page - 1) * limit),
            ).fetchall()
        return [_invoice(r) for r in rows], int(total)

    def save_paid(self, invoice: Invoice, event: DomainEvent) -> None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute(
                "UPDATE billing.invoice SET status = %s, provider_reference = %s, paid_at = %s, updated_at = %s "
                "WHERE id = %s",
                (invoice.status.value, invoice.provider_reference, invoice.paid_at, invoice.updated_at, invoice.id),
            )
            _write_event(conn, event)


def _write_event(conn: psycopg.Connection, event: DomainEvent) -> None:
    conn.execute(
        "INSERT INTO billing.outbox (aggregate_type, aggregate_id, event_type, payload, occurred_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (event.aggregate_type, event.aggregate_id, event.event_type, Jsonb(event.payload), event.occurred_at),
    )


def _values(i: Invoice) -> tuple:
    return (
        i.id,
        i.student_id,
        i.student_name,
        i.term,
        i.amount_cents,
        i.status.value,
        i.provider_reference,
        i.paid_at,
        i.created_at,
        i.updated_at,
    )


def _invoice(row: dict) -> Invoice:
    return Invoice(
        id=row["id"],
        student_id=row["student_id"],
        student_name=row["student_name"],
        term=row["term"],
        amount_cents=int(row["amount_cents"]),
        status=InvoiceStatus(row["status"]),
        provider_reference=row["provider_reference"],
        paid_at=row["paid_at"].astimezone(UTC) if row["paid_at"] else None,
        created_at=row["created_at"].astimezone(UTC),
        updated_at=row["updated_at"].astimezone(UTC),
    )
