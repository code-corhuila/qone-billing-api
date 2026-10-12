"""The composition root (Annex C): the only module that knows every concrete type and every
limit. It reads the environment, builds the adapters and hands the ports to the application."""

import logging
import os
import sys
from datetime import datetime

from billing.adapter.inbound.http.app import create_app
from billing.adapter.inbound.http.auth import TokenVerifier
from billing.adapter.outbound.payment.simulated import SimulatedPaymentProvider
from billing.adapter.outbound.persistence.memory import InMemoryInvoiceStore
from billing.adapter.outbound.runtime import SystemClock, Uuid4Generator
from billing.application.usecase.invoices import InvoiceService

# Explicit limits (norm 5.3.10, Annex C), declared here with their values.
DB_POOL_MAX = 10
DB_WAIT_SECONDS = 5.0
DB_STATEMENT_TIMEOUT_MS = 5000
HTTP_KEEP_ALIVE_SECONDS = 60
HTTP_GRACEFUL_SHUTDOWN_SECONDS = 20


class Settings:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        env = os.environ if env is None else env
        self.database_url = env.get("BILLING_DATABASE_URL", "").strip()
        self.public_key = _public_key(env)
        self.current_term = env.get("CURRENT_TERM", "2026-B").strip()
        self.port = int(env.get("PORT", "8000"))
        self.log_level = env.get("LOG_LEVEL", "info").lower()


def _public_key(env: dict[str, str]) -> str:
    """JWT_PUBLIC_KEY as the PEM in one line with literal \\n, or JWT_PUBLIC_KEY_FILE."""
    inline = env.get("JWT_PUBLIC_KEY", "").strip()
    if inline:
        return inline.replace("\\n", "\n")
    path = env.get("JWT_PUBLIC_KEY_FILE", "").strip()
    if path:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    raise SystemExit("JWT_PUBLIC_KEY or JWT_PUBLIC_KEY_FILE is required: the service validates every token itself")


def build_app(settings: Settings | None = None):
    settings = settings or Settings()
    configure_logging(settings.log_level)
    log = logging.getLogger("billing")
    if settings.database_url and settings.database_url != "memory":
        from billing.adapter.outbound.persistence.postgres import PostgresInvoiceStore, connect

        store = PostgresInvoiceStore(
            connect(settings.database_url, DB_POOL_MAX, DB_WAIT_SECONDS, DB_STATEMENT_TIMEOUT_MS)
        )
        log.info("store: postgresql (pool max %s, statement timeout %s ms)", DB_POOL_MAX, DB_STATEMENT_TIMEOUT_MS)
    else:
        store = InMemoryInvoiceStore(_synthetic_invoices())
        log.warning("store: in memory with synthetic invoices (BILLING_DATABASE_URL not set); development only")
    service = InvoiceService(store, SystemClock(), Uuid4Generator(), SimulatedPaymentProvider(), settings.current_term)
    return create_app(service, TokenVerifier(settings.public_key))


def _synthetic_invoices():
    """The seed of qone-billing-db, for a service started without a database."""
    from datetime import UTC
    from uuid import UUID

    from billing.domain.model.invoice import Invoice

    issued_at, paid_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC), datetime(2026, 8, 10, 15, 30, tzinfo=UTC)
    people = [
        ("01", "11111111-1111-4111-8111-111111111111", "Laura Gómez", True),
        ("02", "11111111-1111-4111-8111-111111111112", "Santiago Rojas", False),
        ("03", "11111111-1111-4111-8111-111111111113", "María José Cabrera", True),
        ("04", "11111111-1111-4111-8111-111111111114", "Andrés Pineda", True),
        ("05", "11111111-1111-4111-8111-111111111115", "Valentina Suárez", True),
    ]
    rows = []
    for n, student, name, paid in people:
        invoice = Invoice.issue(
            UUID(f"88888888-8888-4888-8888-8888888888{n}"), UUID(student), name, "2026-B", 185_000_000, issued_at
        )
        rows.append(invoice.pay(f"SIM-000000{n}", paid_at)[0] if paid else invoice)
    return rows


class JsonFormatter(logging.Formatter):
    """One JSON line per record with the traceId (norm 5.3.9)."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        line = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("traceId", "method", "path", "status", "durationMs"):
            if hasattr(record, key):
                line[key] = getattr(record, key)
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").disabled = True  # the service writes its own access line with the traceId
