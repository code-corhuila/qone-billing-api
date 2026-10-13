"""Support for the HTTP and contract tests: an RSA pair generated per test session (no key is
versioned), tokens minted with it, and the application over the in-memory store seeded like
the synthetic data of qone-billing-db."""

import time
from datetime import UTC, datetime
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from billing.adapter.inbound.http.app import create_app
from billing.adapter.inbound.http.auth import TokenVerifier
from billing.adapter.outbound.persistence.memory import InMemoryInvoiceStore
from billing.application.usecase.invoices import InvoiceService
from billing.domain.model.invoice import Invoice
from tests.fakes import FakeProvider, FixedClock, SequenceIds


def _pem(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_PEM = (
    PRIVATE.public_key()
    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    .decode()
)

LAURA = "11111111-1111-4111-8111-111111111111"
SANTIAGO = "11111111-1111-4111-8111-111111111112"
PATRICIA = "33333333-3333-4333-8333-333333333331"
CARLOS = "22222222-2222-4222-8222-222222222221"
WORKFLOW = "44444444-4444-4444-8444-444444444441"
LAURA_INVOICE = "88888888-8888-4888-8888-888888888801"
SANTIAGO_INVOICE = "88888888-8888-4888-8888-888888888802"
ISSUED_AT = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
PAID_AT = datetime(2026, 8, 10, 15, 30, 0, tzinfo=UTC)


def mint(sub: str, role: str, name: str = "", minutes: int = 60, alg: str = "RS256", key=None, **extra) -> str:
    now = int(time.time())
    claims = {"iss": "qone-identity-api", "sub": sub, "role": role, "name": name, "iat": now, "exp": now + minutes * 60}
    claims.update(extra)
    if alg == "HS256":
        return jwt.encode(claims, "not-a-secret", algorithm="HS256")
    return jwt.encode(claims, _pem(key or PRIVATE), algorithm=alg)


def bearer(sub: str, role: str, name: str = "", **kw) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(sub, role, name, **kw)}"}


def seed() -> list[Invoice]:
    laura = Invoice.issue(UUID(LAURA_INVOICE), UUID(LAURA), "Laura Gómez", "2026-B", 185_000_000, ISSUED_AT)
    laura, _ = laura.pay("SIM-00000001", PAID_AT)
    santiago = Invoice.issue(UUID(SANTIAGO_INVOICE), UUID(SANTIAGO), "Santiago Rojas", "2026-B", 185_000_000, ISSUED_AT)
    return [laura, santiago]


def make_client() -> tuple[TestClient, InMemoryInvoiceStore]:
    store = InMemoryInvoiceStore(seed())
    service = InvoiceService(store, FixedClock(), SequenceIds(start=10), FakeProvider(), current_term="2026-B")
    app = create_app(service, TokenVerifier(PUBLIC_PEM))
    return TestClient(app, raise_server_exceptions=False), store
