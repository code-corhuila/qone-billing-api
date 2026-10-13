"""Routes, validation at the border and response objects of BI-01..BI-06
(07-api/contracts/openapi/qone-billing-api.yaml). The domain entity is never serialized
directly: `represent` builds the camelCase representation (Annex C)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from billing.application.port.inbound.caller import Caller
from billing.application.port.inbound.invoices import DEFAULT_LIMIT, InvoiceUseCases, IssueInvoice
from billing.application.usecase.invoices import KEY_MAX, KEY_MIN
from billing.domain.model.errors import FieldError, ValidationError
from billing.domain.model.invoice import Invoice

PREFIX = "/api/v1/billing"
router = APIRouter(prefix=PREFIX)


class IssueInvoiceBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    studentId: StrictStr  # noqa: N815 - the contract's camelCase
    studentName: StrictStr  # noqa: N815
    term: StrictStr
    amountCents: StrictInt  # noqa: N815 - an integer in cents; a decimal is 400 (norm 5.4.3)


def use_cases(request: Request) -> InvoiceUseCases:
    return request.app.state.use_cases


def caller(request: Request) -> Caller:
    return request.app.state.verifier.verify(request.headers.get("Authorization"))


UseCases = Annotated[InvoiceUseCases, Depends(use_cases)]
Current = Annotated[Caller, Depends(caller)]


@router.get("/health")
def health(request: Request):
    return {"status": "ok", "service": request.app.state.service, "version": request.app.state.version}


@router.get("/invoices/me")
def my_invoices(
    who: Current,
    service: UseCases,
    page: int = Query(1),
    limit: int = Query(DEFAULT_LIMIT),
    term: str | None = Query(None),
):
    result = service.my_invoices(who, term, page, limit)
    return {
        "data": [represent(i) for i in result.items],
        "meta": {"page": result.page, "limit": result.limit, "total": result.total, "totalPages": result.total_pages},
    }


@router.post("/invoices")
def issue(body: IssueInvoiceBody, who: Current, service: UseCases, request: Request):
    # The border names every invalid input it can see at once: the header and the id together.
    key = request.headers.get("Idempotency-Key", "")
    details: list[FieldError] = []
    if not KEY_MIN <= len(key) <= KEY_MAX:
        details.append(FieldError("Idempotency-Key", "header required, 8 to 128 characters"))
    try:
        student_id = parse_uuid(body.studentId, "studentId")
    except ValidationError as error:
        details.extend(error.details)
    if details:
        raise ValidationError(details)
    result = service.issue(who, IssueInvoice(student_id, body.studentName, body.term, body.amountCents), key)
    if not result.created:
        return JSONResponse(represent(result.invoice), status_code=200)
    location = f"{PREFIX}/invoices/{result.invoice.id}"
    return JSONResponse(represent(result.invoice), status_code=201, headers={"Location": location})


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, who: Current, service: UseCases):
    return represent(service.get(who, parse_uuid(invoice_id, "id")))


@router.post("/invoices/{invoice_id}/pay")
def pay(invoice_id: str, who: Current, service: UseCases):
    return represent(service.pay(who, parse_uuid(invoice_id, "id")))


@router.get("/students/{student_id}/invoices/current")
def current_of(student_id: str, who: Current, service: UseCases):
    return represent(service.current_of(who, parse_uuid(student_id, "studentId")))


def parse_uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValidationError([FieldError(field, "must be a UUID")]) from None


def rfc3339(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def represent(invoice: Invoice) -> dict:
    return {
        "id": str(invoice.id),
        "studentId": str(invoice.student_id),
        "studentName": invoice.student_name,
        "term": invoice.term,
        "amountCents": invoice.amount_cents,
        "status": invoice.status.value,
        "providerReference": invoice.provider_reference,
        "paidAt": rfc3339(invoice.paid_at) if invoice.paid_at else None,
        "createdAt": rfc3339(invoice.created_at),
    }
