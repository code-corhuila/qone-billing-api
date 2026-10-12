# qone-billing-api

> billing bounded context: service API

Part of the **Qampus (Quorum One)** distributed system — team `quorum-one`, Grupo 1.
Governance and documentation live in [`qone-docs`](https://github.com/code-corhuila/qone-docs).

## Purpose

The service of the **billing** domain (course norm 5.3, Annex C): the term invoice of a
student, its simulated payment and the tuition state the enrollment saga checks first
(ADR-008, step `check-tuition`). Python 3.12 + FastAPI, hexagonal (ADR-007): the domain and
the use cases import no framework and no driver; a test enforces it.

- Contract: `07-api/contracts/openapi/qone-billing-api.yaml` (BI-01..BI-06) in `qone-docs`.
- Data: `qone-billing-db` owns the schema `billing`; this service never versions it.
- Piece page: `09-microservices/services/05-billing-api/README.md`. Story: `code-corhuila/qone-docs#43` (HU-BIL-001).

## Layout (Annex C, Python)

```
src/billing/
├── domain/model/            invoice.py (aggregate), events.py, errors.py      - depends on nothing
├── application/port/        inbound/ (use cases offered) · outbound/ (store, clock, ids, payments)
├── application/usecase/     the operations of BI-02..BI-06 and the authorization by role
└── adapter/
    ├── inbound/http/        app.py, auth.py (RS256), errors.py (envelope), router.py
    └── outbound/            persistence/ (memory, postgres), payment/ (simulated provider)
apps/api/__main__.py         composition root: the only module that knows every concrete type and limit
tests/                       test_invoice_model.py, test_invoices.py, test_http.py, test_architecture.py,
                             test_postgres_integration.py (skipped without TEST_DATABASE_URL)
```

## Rules it keeps

- One invoice per student and term (INV-BIL-001): checked by the use case, guaranteed by the
  unique index of `qone-billing-db`.
- `pay` moves `ISSUED` to `PAID` exactly once; paying again returns the same invoice with `200`
  (INV-BIL-002, D-04).
- Money is an integer in COP cents end to end (norm 5.4.3).
- Every creation is idempotent by `Idempotency-Key` (norm 5.3.8); every change writes its event
  to the outbox in the same transaction (norm 5.3.11).

## How to run it

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check .
python -m pytest                                   # domain, use cases, HTTP, architecture
```

The HTTP server, its configuration (`.env.example`) and the PostgreSQL adapter arrive with the
next pull requests of HU-BIL-001.

## Branching

Three permanent branches. **None of them accepts a direct commit** — you enter through a child
branch and leave through a Pull Request.

```
develop  <--PR--  feat/... fix/... chore/...
qa       <--PR--  qa/...
main     <--PR--  release/...  hotfix/...
```

Promotion happens **by re-application** (`git cherry-pick -x`), never by merging one permanent
branch into another: `merge develop -> qa` and `merge qa -> main` do not exist in this model.

`main` requires **1 approval from `ariel5253`**. On `develop` and `qa` the team sets its own review
rule.

Full policy: `00-governance/branching-policy.md` in `qone-docs`.
