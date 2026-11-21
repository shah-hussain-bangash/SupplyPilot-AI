# SupplyPilot AI

**B2B procurement and supplier collaboration for industrial materials.**

**Featured case study:** [SupplyPilot AI Case Study — controlled sourcing, purchasing and fulfillment](docs/case-study/SUPPLYPILOT_CASE_STUDY.md). Explore the architecture, optimization model, exact-payload approval, timeout reconciliation, invoice rechecks, verified PostgreSQL/CI evidence and enterprise delivery gates.

A full-stack engineering project connecting document review, supplier quotations, sourcing decisions, approvals, purchasing, receiving, invoice matching, and audit history.

> Development prototype. Supplier records are synthetic and external purchasing uses a local ERP simulator. This is not a production procurement service.

## Workflow

```mermaid
flowchart LR
    A[Upload source] --> B[Review RFQ]
    B --> C[Invite suppliers]
    C --> D[Submit quotations]
    D --> E[Technical review]
    E --> F[Optimize sourcing]
    F --> G[Manager approval]
    G --> H[Queue purchase]
    H --> I[Dispatch or reconcile]
    I --> J[Receive and inspect]
    J --> K[Match or recheck invoices]
    K --> L[Close order]
```

## Implemented capabilities

- Public website and authenticated workspace with role-based navigation.
- RFQ revision history, supplier invitations, supplier-owned evidence and quotations.
- Text-based PDF/TXT/CSV/JSON ingestion and human technical review.
- OR-Tools sourcing optimization with capacity, MOQ, pack size, delivery, freight and budget constraints.
- Exact-decision approval, authority limits, expiry and separate purchasing roles.
- Transactional execution intents, simulator idempotency and timeout reconciliation.
- Partial receiving, accepted/rejected/quarantine quantities, invoice matching and recheck history.
- Exception resolution, closure guards and scoped audit events.
- PostgreSQL migrations through `0007_proc_fulfillment`, forced tenant RLS and synchronized relational projections.
- Supplier, RFQ, quotation, purchase-order, receipt and invoice reads use relational fields while retaining source history and metadata. Writes and remaining record kinds retain the aggregate record model.
- SQLite mode for a fresh local demo and automated tests.

## Stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, CSS |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy |
| Database | PostgreSQL, Alembic; SQLite demo mode |
| Workflow and optimization | LangGraph, OR-Tools CP-SAT |
| Authentication | Password hashing, JWT; optional OIDC verification |
| Document parsing | pypdf and text parsers |
| Verification | pytest, HTTP API rehearsals, Playwright scripts |
| Local infrastructure | Docker Compose, durable local ERP simulator |

## Run a fresh Windows demo

Prerequisites: Python 3.12+, Node.js 22+, npm and Git. Open this repository in Cursor or another editor.

```powershell
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r '.\backend\requirements.txt'
Set-Location '.\frontend'
npm.cmd ci
npm.cmd run build
Set-Location '..'
$env:DEMO_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'Choose a demo password with at least 12 characters' -AsSecureString)).Password
$env:TOKEN_SECRET = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
Set-Location '.\backend'
& '..\.venv\Scripts\python.exe' -m supplypilot.manage migrate
& '..\.venv\Scripts\python.exe' -m supplypilot.manage seed
& '..\.venv\Scripts\python.exe' -m uvicorn supplypilot.main:app --host 127.0.0.1 --port 0
```

Open the exact address printed by Uvicorn, select **Portal login**, and keep the terminal open. These commands initialize the SQLite demo, not the PostgreSQL Alembic chain. The frontend must be built before opening the portal.

Use `buyer` for team access or `supplier-gulf` for supplier access, with the password you chose. Other seeded accounts: `technical`, `manager`, `warehouse`, `finance`, `planner`, `auditor`, `admin`, `supplier-desert`, `supplier-budget`, and the isolated `other-buyer` tenant. Existing accounts retain their existing password on repeat seeding.

Python reads environment variables directly; `.env.example` is a template and is not loaded automatically.

## PostgreSQL development

`compose.dev-db.yaml` starts local-only PostgreSQL on a dynamically allocated host port. Creating separate runtime and migration roles, setting passwords and granting privileges is required before running migrations; Compose alone does not complete setup.

The existing development configuration expects database `supplypilot_dev`, runtime role `supplypilot_app`, and migration role `supplypilot_migrator`. Set `SUPPLYPILOT_DB_PORT` to the published database port and run Alembic from `backend`; its environment prompts for the migrator password. After database setup, `scripts/start_postgres_dev.py` prompts for the runtime password, checks permissions, and prints the portal URL.

Passwords and existing databases are not included. See `docs/reference/TENANT_ISOLATION.md` for context. Reference documents describe earlier milestones; this README describes the uploaded installed snapshot.

## Tests

After installing backend dependencies, run from the repository root:

```powershell
Set-Location '.\backend'
& '..\.venv\Scripts\python.exe' -m pytest
```

The pytest suite uses temporary SQLite data and adapter regression cases. To run the PostgreSQL acceptance suite from the repository root, with Docker running:

```powershell
& '.\.venv\Scripts\python.exe' '.\scripts\test_postgres.py' --docker --concurrency
```

This creates a separate PostgreSQL 17 container with a randomly assigned local port and temporary credentials, applies the full Alembic migration chain, seeds synthetic accounts, checks RLS and protected grants, and replays procurement through receipt, invoice recheck and order closure. It also compares relational responses with authoritative records and tests supplier/tenant scope and stale projections. The runner removes its own container after success or failure and never connects to the development database. It requires Docker access and does not accept a database URL.

With `--concurrency`, pairs of API requests are held behind a database row lock until PostgreSQL confirms that both are waiting, then released together. The suite checks duplicate execution and reconciliation, competing receipts and invoices, exact ledger totals, and audit counts. These are targeted race checks, not a load benchmark.

GitHub CI runs this PostgreSQL check separately from the backend pytest suite and frontend build. Historical backup/restore rehearsals remain separate; this suite does not claim restore, browser, concurrency/load or live ERP coverage.

## Structure

```text
backend/supplypilot/    API, access control, domain workflow, optimizer, simulator
backend/migrations/    Reviewed PostgreSQL migration chain
backend/tests/         Automated behavioral tests
frontend/src/          Public website and procurement portal
frontend/public/       Website image assets
frontend/tests/        Browser test scripts
scripts/               Local setup, test and startup helpers
docs/reference/        Architecture, requirements and earlier milestone notes
```

## Remaining work

Live ERP, email dispatch, payments, freight/tax accounting, production identity provisioning, OCR, semantic RAG, trained forecasting, governed model releases and cloud operational acceptance remain further work. A private model gateway contract exists, but no active LLM provider, embedding model or vector retrieval deployment is claimed.

Tenant RLS relies on trusted application-set context and does not protect against compromise of the shared runtime credential. Supplier restrictions also rely on application authorization. Audit events are protected from runtime update/delete, but external tamper-resistant storage is not implemented.

Local databases, document uploads, backups, credentials, dependencies and compiled frontend output are excluded from source control.
