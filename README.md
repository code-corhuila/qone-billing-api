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
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scriptsctivate
pip install -e ".[dev]"
ruff check .
python -m pytest                                   # domain, use cases, HTTP, contract, architecture
cp .env.example .env                               # JWT_PUBLIC_KEY (or _FILE), BILLING_DATABASE_URL, CURRENT_TERM
python -m apps.api                                 # http://localhost:8000/api/v1/billing/health
```

Without `BILLING_DATABASE_URL` the service starts over an in-memory store with the synthetic
invoices of the seed (development only; it says so in the log). With it, the store is
`qone-billing-db`: start that repository's compose, run its Flyway runner, and point the URL at
it. The public key is the one `qone-infra/scripts/dev-keys.sh` writes; the service never holds
the private key (norm 5.3.7).

Integration tests against the real schema (Annex C) run only when `TEST_DATABASE_URL` is set:

```bash
TEST_DATABASE_URL=postgresql://billing:password@localhost:5432/billing python -m pytest tests/test_postgres_integration.py
```

Container image and compose (`deploy/`, Annex G): `docker build -f deploy/Dockerfile -t
qone-billing-api:dev .`. `deploy/compose.yml` is what `qone-infra` includes: `expose` only,
after `billing-db` is healthy.

Explicit limits (norm 5.3.10), declared in `apps/api/factory.py`:

| Limit | Value |
|---|---|
| Connection pool | 10 connections, 5 s wait |
| Statement timeout | 5 s |
| Keep-alive | 60 s |
| Graceful shutdown | 20 s |
| Header read | imposed by the gateway (NGINX `client_header_timeout`) |

Every log line is JSON with the `traceId` of the request (norm 5.3.9); the detail of a 500
goes there, never to the client.

`scripts/sync-contracts.sh [ref]` refreshes the contract copies in
`contracts/openapi/` from `qone-docs` with the GitHub CLI.

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
