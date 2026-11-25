# SupplyPilot AI

**B2B procurement and supplier collaboration for industrial materials.**

**Featured case study:** [SupplyPilot AI Case Study â€” controlled sourcing, purchasing and fulfillment](docs/case-study/SUPPLYPILOT_CASE_STUDY.md). Explore the architecture, optimization model, exact-payload approval, timeout reconciliation, invoice rechecks, verified PostgreSQL/CI evidence and enterprise delivery gates.

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
- PostgreSQL migrations through `0012_proc_document_jobs`, forced tenant RLS and synchronized relational projections.
- Supplier, RFQ, quotation, purchase-order, receipt, invoice, inventory, sourcing-plan, exception and completed document-job reads use relational fields while retaining source history and metadata. Writes and remaining record kinds retain the aggregate record model.
- Read-only stock-balance and inbound-delivery projections synchronized from authoritative inventory records. Inventory portal reads use these projections and retain source metadata and extensions.
- Read-only sourcing-plan headers, complete payload snapshots and approval metadata synchronized from authoritative records. Plan portal reads retain the aggregate path; authorization and digest recomputation remain application responsibilities.
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
& '.\.venv\Scripts\python.exe' '.\scripts\test_postgres.py' --docker --concurrency --restore-check
```

This creates a separate PostgreSQL 17 container with a randomly assigned local port and temporary credentials, applies migrations through `0007`, seeds synthetic accounts, upgrades through `0008` to test the inventory backfill, creates a real API sourcing plan before upgrading through `0009` to test plan backfill, creates and resolves an API exception before upgrading through `0010` to test exception backfill, upgrades through `0011` with pre-existing reviewable and quarantined API documents, upgrades through `0012` with an existing API extraction job, checks RLS and protected grants, and replays procurement through receipt, invoice recheck and order closure. Exception storage preserves manual and automatic resolution fields separately and full source snapshots, enforces tenant-qualified resource/evidence links, and tests validation, deletion and rollback. Owner and resolver fields remain historical metadata; authorization remains in the application. Exception collection and detail reads use synchronized fields and full snapshots; manual and automatic resolution names remain distinct, and missing or stale projections fail closed. Document storage checks preserve metadata, ordered parsed pages, Unicode/blank text, quarantine states, tenant scope and transactional rollback. File bytes, parsing, downloads and portal document reads retain their existing paths; scan flags remain metadata, not proof of scanning. Completed document-job storage preserves full extraction results, candidate order and source anchors, and enforces tenant-qualified document links and immutable job/document/execution identity. Its current completed-state formats cover deterministic graph results and synthetic gateway-contract fixtures; tests do not call a live model. Processing-result collection and detail reads use `proc_document_jobs`, preserving complete result JSON, source anchors, review flags and metadata extensions. Suppliers cannot read jobs, including jobs for their own uploads; other tenants cannot read them. Missing/stale headers or candidate-count disagreement fail closed. The read cutover leaves application authority and extraction behavior unchanged. Inventory acceptance cases cover backfill parity, balance validation, ordered inbound deliveries, tenant isolation and rollback. Plan read checks preserve full sourcing snapshots, approval and execution metadata, expired historical plans and timestamp precision, and reject missing or stale plan projections. It also compares relational responses with authoritative records and tests supplier/tenant scope and stale projections. The runner removes its own container after success or failure and never connects to the development database. It requires Docker access and does not accept a database URL.

With `--concurrency`, pairs of API requests are held behind a database row lock until PostgreSQL confirms that both are waiting, then released together. The suite checks duplicate execution and reconciliation, competing receipts and invoices, exact ledger totals, and audit counts. These are targeted race checks, not a load benchmark.

GitHub CI runs this PostgreSQL check separately from the backend pytest suite and frontend build. With `--restore-check`, the synthetic database is dumped and restored into a second database in the same temporary container. The suite compares all public table rows, columns, constraints, indexes, owners, RLS policies, functions, triggers and table grants, then checks tenant visibility and restricted runtime access in the restored database. The cluster roles already exist in that container. Historical private backup rehearsals remain separate; this suite does not cover file uploads, role recovery into a new cluster, browser behavior, load testing or live ERP recovery.

## Browser acceptance

From the repository root, with Node.js installed:

```powershell
& '.\.venv\Scripts\python.exe' '.\scripts\test_browser.py' --prepare
```

`--prepare` installs locked frontend packages, builds the portal and installs Chromium. On Linux, install browser system dependencies with `npx playwright install --with-deps chromium` from `frontend` first, as the CI job does. Subsequent runs can omit `--prepare`.

The runner creates temporary SQLite data and generated demo credentials, starts its own loopback server on a dynamic port, and opens the actual portal in headless Chromium. It checks 18 buyer screens and seven roles through technical review, approval, timeout reconciliation, receiving, invoice mismatch/recheck, closure, supplier scope and auditor access. It also opens a mobile viewport. There are no mocked API responses. Reports and synthetic screenshots go to ignored `test-results/browser/`; browser and server cleanup run after success or failure.

GitHub runs this browser job alongside the backend, PostgreSQL and frontend build jobs. Browser coverage uses SQLite; the separate PostgreSQL suite covers relational reads, concurrency and restore. This is not cross-browser, accessibility or comprehensive visual acceptance.

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
