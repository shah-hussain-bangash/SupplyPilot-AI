# Accepted implementation boundary and traceability

This is a proposed scope, not owner-signed enterprise acceptance. Use `IMPLEMENTATION_STATUS.json` as the machine-readable feature ledger; `sources/manifest.json` lists every readable local project PDF and the inaccessible network originals. Requirement IDs F01-F22 and phase IDs P0-P12 follow the prior local master plan. Tests have descriptive names rather than pretending the old proposed Txx suite already existed.

## Local baseline

One industrial-material category, one local entity/warehouse, one currency (AED), integer pieces, exact specification comparison, private local documents and a simulated ERP. The first demonstrable case is source evidence → validated requirements → supplier eligibility → inventory shortage → independently checked allocation → manager approval → durable outbox → uncertain create recovery → accepted receipt → invoice match → closure.

Business rules are demonstration defaults pending owner approval: one-hour stock freshness, 24-hour approval expiry, manager ceiling AED 20,000, exact material invoice matching and compulsory manual technical evidence review. They are not universal industry policies. Change these only through a reviewed policy revision and tests.

## Business invariants

- Identity and roles come from a verified token and active account. Tenant/supplier scope applies to direct IDs, lists, files and retrieval.
- Mutations compare expected_revision; concurrent changes fail without partial business/audit/outbox commits.
- Reviewed lines reference a successfully parsed original document; raw source and hashes remain available. Critical quantities/specifications need human review.
- Missing mandatory specifications or certificate proof remain unknown; mismatches are noncompliant. Neither can win an award.
- Quote revisions reset eligibility and supersede unexecuted plans; source snapshots and historical payloads are retained.
- Plans freeze source revisions, evidence hashes and commercial payload. Execution rechecks current sources, authority, expiry and exact approved hash.
- A stable key refers to one execution payload. Timeout after possible provider create requires reconciliation; never assume exactly once for arbitrary providers.
- Receipts track accepted/rejected/quarantine separately, and only accepted goods increase usable stock. Cumulative matched invoices cannot exceed accepted quantity.
- Closure requires full accepted quantity, matched material invoices and no relevant open exception. Amendments/reversals require a future controlled process.
- Models may propose candidates; they cannot approve, post orders, release stock, make payments or train/deploy themselves.

## No inferred completion

No real-format labeled document benchmark, live model quality, ERP sandbox transaction, Docker deployment, SSO tenant integration, distributed worker recovery, restore drill, performance SLO or measured business pilot was validated. Source preparation is not proof of these gates. The PDF report records their remaining work and priority.

## Validation commands

`cd backend; python -m pytest` verifies implemented invariant scenarios on an isolated database. `cd frontend; npm ci; npm run build` checks types and bundles the application. `frontend/tests/smoke.cjs` drives the connected local UI through six roles. Recorded evidence is included; see README for reproduction prerequisites.
