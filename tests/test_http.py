"""HTTP level (Annex C): the checks of norm 5.3.12 the teacher runs by HTTP, automated against
this service's resources, with the server in memory and the in-memory store."""

import pytest

from tests.http_support import (
    CARLOS,
    LAURA,
    LAURA_INVOICE,
    OTHER_PRIVATE,
    PATRICIA,
    SANTIAGO,
    SANTIAGO_INVOICE,
    WORKFLOW,
    bearer,
    make_client,
    mint,
)

BASE = "/api/v1/billing"
KEY = {"Idempotency-Key": "invoice-6f1d2c3e-9b7a-4e1f-8c2d-0a1b2c3d4e5f"}
NEW_STUDENT = "11111111-1111-4111-8111-111111111119"
VALID_BODY = {"studentId": NEW_STUDENT, "studentName": "Nuevo Estudiante", "term": "2026-B", "amountCents": 185000050}


@pytest.fixture
def client():
    client, _ = make_client()
    return client


def admin():
    return bearer(PATRICIA, "ADMIN", "Patricia Mora")


def laura():
    return bearer(LAURA, "STUDENT", "Laura Gómez")


def santiago():
    return bearer(SANTIAGO, "STUDENT", "Santiago Rojas")


class TestAuthentication:
    def test_health_answers_without_a_token(self, client):
        r = client.get(f"{BASE}/health")
        assert r.status_code == 200 and r.json() == {"status": "ok", "service": "qone-billing-api", "version": "2.0.0"}

    def test_without_a_token_is_401(self, client):
        r = client.get(f"{BASE}/invoices/me")
        assert r.status_code == 401 and r.json()["error"] == "UNAUTHORIZED"

    def test_an_alg_other_than_rs256_is_401(self, client):
        token = mint(LAURA, "STUDENT", alg="HS256")
        r = client.get(f"{BASE}/invoices/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_an_expired_token_is_401(self, client):
        r = client.get(f"{BASE}/invoices/me", headers=bearer(LAURA, "STUDENT", minutes=-5))
        assert r.status_code == 401

    def test_a_token_signed_with_another_key_is_401(self, client):
        r = client.get(f"{BASE}/invoices/me", headers=bearer(LAURA, "STUDENT", key=OTHER_PRIVATE))
        assert r.status_code == 401

    def test_a_token_without_exp_or_sub_is_401(self, client):
        token = mint(LAURA, "STUDENT", exp=None)
        r = client.get(f"{BASE}/invoices/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_a_valid_token_with_the_wrong_role_is_403(self, client):
        r = client.get(f"{BASE}/invoices/me", headers=bearer(CARLOS, "PROFESSOR", "Carlos Ramírez"))
        assert r.status_code == 403 and r.json()["error"] == "FORBIDDEN"


class TestEnvelopeAndCorrelation:
    def test_a_malformed_id_is_400_with_the_envelope(self, client):
        r = client.get(f"{BASE}/invoices/not-a-uuid", headers=laura())
        body = r.json()
        assert r.status_code == 400 and body["error"] == "VALIDATION_ERROR"
        assert {"error", "message", "traceId"} <= body.keys()
        assert body["details"] == [{"field": "id", "message": "must be a UUID"}]

    def test_the_trace_id_repeats_the_received_correlation_id_and_the_header_comes_back(self, client):
        r = client.get(f"{BASE}/invoices/not-a-uuid", headers={**laura(), "X-Correlation-Id": "e2e-saga-1"})
        assert r.json()["traceId"] == "e2e-saga-1"
        assert r.headers["X-Correlation-Id"] == "e2e-saga-1"

    def test_without_a_correlation_id_the_service_generates_one(self, client):
        r = client.get(f"{BASE}/health")
        generated = r.headers["X-Correlation-Id"]
        assert len(generated) == 36

    def test_a_nonexistent_resource_is_404(self, client):
        r = client.get(f"{BASE}/invoices/00000000-0000-4000-8000-000000000000", headers=laura())
        assert r.status_code == 404 and r.json()["error"] == "NOT_FOUND"

    def test_a_nonexistent_route_is_404_with_the_envelope(self, client):
        r = client.get(f"{BASE}/nothing-here", headers=laura())
        assert r.status_code == 404 and r.json()["error"] == "NOT_FOUND" and "traceId" in r.json()


class TestValidationAtTheBorder:
    def test_an_invalid_body_names_every_field_including_the_idempotency_key(self, client):
        bad = {"studentId": "x", "studentName": "L", "term": "2026", "amountCents": 0}
        r = client.post(f"{BASE}/invoices", json=bad, headers=admin())
        body = r.json()
        assert r.status_code == 400 and body["error"] == "VALIDATION_ERROR"
        assert [d["field"] for d in body["details"]] == ["Idempotency-Key", "studentId"]
        r = client.post(f"{BASE}/invoices", json={**bad, "studentId": NEW_STUDENT}, headers={**admin(), **KEY})
        assert [d["field"] for d in r.json()["details"]] == ["studentName", "term", "amountCents"]

    def test_money_with_decimals_is_400(self, client):
        r = client.post(f"{BASE}/invoices", json={**VALID_BODY, "amountCents": 1850000.5}, headers={**admin(), **KEY})
        assert r.status_code == 400 and [d["field"] for d in r.json()["details"]] == ["amountCents"]

    def test_malformed_json_is_400(self, client):
        r = client.post(
            f"{BASE}/invoices", content="{not json", headers={**admin(), **KEY, "Content-Type": "application/json"}
        )
        assert r.status_code == 400 and r.json()["error"] == "VALIDATION_ERROR"

    def test_a_missing_field_is_400(self, client):
        r = client.post(f"{BASE}/invoices", json={"studentId": NEW_STUDENT}, headers={**admin(), **KEY})
        assert r.status_code == 400 and {"studentName", "term", "amountCents"} <= {
            d["field"] for d in r.json()["details"]
        }


class TestIdempotentCreation:
    def test_the_first_send_is_201_with_a_uuid_and_location(self, client):
        r = client.post(f"{BASE}/invoices", json=VALID_BODY, headers={**admin(), **KEY})
        assert r.status_code == 201
        body = r.json()
        assert len(body["id"]) == 36 and r.headers["Location"] == f"{BASE}/invoices/{body['id']}"
        assert body["status"] == "ISSUED" and body["amountCents"] == 185000050

    def test_a_retry_with_the_same_key_is_200_with_the_same_id(self, client):
        first = client.post(f"{BASE}/invoices", json=VALID_BODY, headers={**admin(), **KEY}).json()
        again = client.post(f"{BASE}/invoices", json=VALID_BODY, headers={**admin(), **KEY})
        assert again.status_code == 200 and again.json()["id"] == first["id"]

    def test_a_second_invoice_for_the_same_student_and_term_is_422(self, client):
        body = {**VALID_BODY, "studentId": LAURA, "studentName": "Laura Gómez"}
        r = client.post(
            f"{BASE}/invoices", json=body, headers={**admin(), "Idempotency-Key": "invoice-second-intention-1"}
        )
        assert r.status_code == 422 and r.json()["error"] == "BUSINESS_RULE_VIOLATION"
        assert r.json()["message"].startswith("INV-BIL-001")

    def test_a_student_may_not_issue(self, client):
        r = client.post(f"{BASE}/invoices", json=VALID_BODY, headers={**laura(), **KEY})
        assert r.status_code == 403


class TestRepresentationAndTransitions:
    def test_the_representation_is_camel_case_with_rfc3339_dates(self, client):
        r = client.get(f"{BASE}/invoices/{LAURA_INVOICE}", headers=laura())
        assert r.status_code == 200
        assert r.json() == {
            "id": LAURA_INVOICE,
            "studentId": LAURA,
            "studentName": "Laura Gómez",
            "term": "2026-B",
            "amountCents": 185000000,
            "status": "PAID",
            "providerReference": "SIM-00000001",
            "paidAt": "2026-08-10T15:30:00Z",
            "createdAt": "2026-08-01T12:00:00Z",
        }

    def test_another_students_invoice_is_404_and_an_admin_or_service_reads_it(self, client):
        assert client.get(f"{BASE}/invoices/{LAURA_INVOICE}", headers=santiago()).status_code == 404
        assert client.get(f"{BASE}/invoices/{LAURA_INVOICE}", headers=admin()).status_code == 200
        assert client.get(f"{BASE}/invoices/{LAURA_INVOICE}", headers=bearer(WORKFLOW, "SERVICE")).status_code == 200

    def test_paying_moves_to_paid_and_paying_again_returns_the_same_invoice(self, client):
        first = client.post(f"{BASE}/invoices/{SANTIAGO_INVOICE}/pay", headers=santiago())
        assert first.status_code == 200 and first.json()["status"] == "PAID"
        assert first.json()["providerReference"].startswith("SIM-") and first.json()["paidAt"] is not None
        again = client.post(f"{BASE}/invoices/{SANTIAGO_INVOICE}/pay", headers=santiago())
        assert again.status_code == 200 and again.json() == first.json()

    def test_only_the_owner_pays(self, client):
        assert client.post(f"{BASE}/invoices/{SANTIAGO_INVOICE}/pay", headers=laura()).status_code == 404
        assert client.post(f"{BASE}/invoices/{SANTIAGO_INVOICE}/pay", headers=admin()).status_code == 403

    def test_the_current_term_invoice_for_the_saga(self, client):
        r = client.get(f"{BASE}/students/{SANTIAGO}/invoices/current", headers=bearer(WORKFLOW, "SERVICE"))
        assert r.status_code == 200 and r.json()["id"] == SANTIAGO_INVOICE and r.json()["status"] == "ISSUED"
        assert client.get(f"{BASE}/students/{NEW_STUDENT}/invoices/current", headers=admin()).status_code == 404
        assert client.get(f"{BASE}/students/{SANTIAGO}/invoices/current", headers=santiago()).status_code == 403


class TestBoundedListing:
    def test_the_list_is_data_and_meta_with_the_defaults(self, client):
        r = client.get(f"{BASE}/invoices/me", headers=laura())
        body = r.json()
        assert r.status_code == 200 and set(body) == {"data", "meta"}
        assert body["meta"] == {"page": 1, "limit": 20, "total": 1, "totalPages": 1}
        assert body["data"][0]["id"] == LAURA_INVOICE

    def test_the_meta_repeats_the_values_and_the_page_is_bounded(self, client):
        r = client.get(f"{BASE}/invoices/me?page=2&limit=1", headers=laura())
        assert r.json()["meta"] == {"page": 2, "limit": 1, "total": 1, "totalPages": 1} and r.json()["data"] == []

    def test_newest_first(self, client):
        client.post(
            f"{BASE}/invoices",
            json={**VALID_BODY, "studentId": LAURA, "studentName": "Laura Gómez", "term": "2027-A"},
            headers={**admin(), **KEY},
        )
        r = client.get(f"{BASE}/invoices/me", headers=laura())
        assert [i["term"] for i in r.json()["data"]] == ["2027-A", "2026-B"]

    @pytest.mark.parametrize("query", ["limit=101", "limit=0", "page=0", "limit=abc", "term=2026"])
    def test_out_of_range_or_unknown_values_are_400(self, client, query):
        r = client.get(f"{BASE}/invoices/me?{query}", headers=laura())
        assert r.status_code == 400 and r.json()["error"] == "VALIDATION_ERROR"

    def test_the_term_filter_works(self, client):
        r = client.get(f"{BASE}/invoices/me?term=2025-A", headers=laura())
        assert r.json()["data"] == [] and r.json()["meta"]["total"] == 0
