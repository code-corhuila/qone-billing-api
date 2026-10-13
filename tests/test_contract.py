"""Contract level: the responses of this service validate against the synced copy of
07-api/contracts/openapi/qone-billing-api.yaml, and every path the contract declares is
served. The copies are refreshed with scripts/sync-contracts.sh (qone-docs is the source)."""

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tests.http_support import LAURA, LAURA_INVOICE, PATRICIA, SANTIAGO, SANTIAGO_INVOICE, bearer, make_client

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts" / "openapi"
BILLING = yaml.safe_load((CONTRACTS / "qone-billing-api.yaml").read_text(encoding="utf-8"))
SHARED = yaml.safe_load((CONTRACTS / "_shared.yaml").read_text(encoding="utf-8"))
BASE = "/api/v1/billing"
KEY = {"Idempotency-Key": "invoice-6f1d2c3e-9b7a-4e1f-8c2d-0a1b2c3d4e5f"}


def inline(node, doc):
    """Resolves local and ./_shared.yaml references and turns OpenAPI 3.0 `nullable` into a type union."""
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            source = SHARED if ref.startswith("./_shared.yaml#") else doc
            target = source
            for part in ref.split("#/")[1].split("/"):
                target = target[part]
            return inline(target, source)
        out = {k: inline(v, doc) for k, v in node.items() if k != "nullable"}
        if node.get("nullable"):
            return {"anyOf": [out, {"type": "null"}]}
        return out
    if isinstance(node, list):
        return [inline(v, doc) for v in node]
    return node


def schema(name: str, doc=BILLING):
    return inline(doc["components"]["schemas"][name], doc)


def assert_valid(body, name: str, doc=BILLING):
    errors = list(Draft202012Validator(schema(name, doc), format_checker=FormatChecker()).iter_errors(body))
    assert not errors, [e.message for e in errors]


@pytest.fixture
def client():
    client, _ = make_client()
    return client


def test_every_path_of_the_contract_is_served(client):
    served = set(client.app.openapi()["paths"])  # what the framework itself routes, nested routers included
    for path in BILLING["paths"]:
        pattern = "/api/v1" + path.replace("{id}", "{invoice_id}").replace("{studentId}", "{student_id}")
        assert pattern in served, f"{path} is in the contract but not served"


def test_health_matches_the_shared_health_schema(client):
    assert_valid(client.get(f"{BASE}/health").json(), "Health", SHARED)


def test_an_invoice_matches_the_invoice_schema(client):
    assert_valid(client.get(f"{BASE}/invoices/{LAURA_INVOICE}", headers=bearer(LAURA, "STUDENT")).json(), "Invoice")
    paid = client.post(f"{BASE}/invoices/{SANTIAGO_INVOICE}/pay", headers=bearer(SANTIAGO, "STUDENT")).json()
    assert_valid(paid, "Invoice")


def test_the_page_matches_the_invoice_page_schema(client):
    assert_valid(client.get(f"{BASE}/invoices/me", headers=bearer(LAURA, "STUDENT")).json(), "InvoicePage")


def test_an_issued_invoice_matches_and_the_request_schema_is_what_the_portal_sends(client):
    body = {
        "studentId": "11111111-1111-4111-8111-111111111119",
        "studentName": "Nuevo Estudiante",
        "term": "2026-B",
        "amountCents": 185000050,
    }
    assert_valid(body, "IssueInvoiceRequest")
    r = client.post(f"{BASE}/invoices", json=body, headers={**bearer(PATRICIA, "ADMIN"), **KEY})
    assert r.status_code == 201
    assert_valid(r.json(), "Invoice")


@pytest.mark.parametrize(
    ("method", "path", "headers", "status", "code"),
    [
        ("GET", "/invoices/me?limit=101", {"role": "STUDENT", "sub": LAURA}, 400, "VALIDATION_ERROR"),
        ("GET", "/invoices/me", None, 401, "UNAUTHORIZED"),
        ("GET", "/invoices/me", {"role": "PROFESSOR", "sub": "22222222-2222-4222-8222-222222222221"}, 403, "FORBIDDEN"),
        ("GET", "/invoices/00000000-0000-4000-8000-000000000000", {"role": "STUDENT", "sub": LAURA}, 404, "NOT_FOUND"),
        ("GET", "/no-such-route", {"role": "STUDENT", "sub": LAURA}, 404, "NOT_FOUND"),
    ],
)
def test_every_error_matches_the_shared_error_schema(client, method, path, headers, status, code):
    auth = bearer(headers["sub"], headers["role"]) if headers else {}
    r = client.request(method, f"{BASE}{path}", headers=auth)
    assert r.status_code == status
    body = r.json()
    assert body["error"] == code
    assert_valid(body, "Error", SHARED)
    assert body["error"] in schema("ErrorCode", SHARED)["enum"]


def test_a_business_rule_error_names_its_invariant(client):
    body = {"studentId": LAURA, "studentName": "Laura Gómez", "term": "2026-B", "amountCents": 185000000}
    r = client.post(f"{BASE}/invoices", json=body, headers={**bearer(PATRICIA, "ADMIN"), **KEY})
    assert r.status_code == 422
    assert_valid(r.json(), "Error", SHARED)
    assert r.json()["message"].startswith("INV-BIL-001:")
