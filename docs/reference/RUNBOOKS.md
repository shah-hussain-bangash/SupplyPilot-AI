# Operational handoff

These are reviewed starting procedures to execute in a test environment, not evidence that production recovery has been validated.

## Startup

Run migrations explicitly, seed only in local mode, build the web application, then start the API on loopback. Verify `/health` and a buyer login. Do not seed or reset a production database. Only an approved forward migration may change an existing schema.

## Uncertain order / interrupted worker

Owner: procurement integration operator. Inspect the execution intent, payload hash, stable key, approval and observed provider reference. A processing or uncertain intent must not be reset to pending casually. Use Reconcile in Purchase orders. If the simulator has a matching key, recover its existing external ID. If lookup finds none, remain blocked for manual evidence; the app deliberately does not blind-create another order. For a real ERP, implement provider-specific read-after-write and ambiguous-result procedures before enabling posting.

## Stale data / changed requirements

Owner: buyer/planner. Refresh authoritative ERP data, re-evaluate supplier evidence and regenerate the plan. The local-only stock timestamp button is a simulation, not an ERP sync. Old approvals cannot authorize a changed payload. After execution, open an amendment exception; actual amendment/cancel/return/credit execution is not implemented.

## Quality or invoice failure

Owner: warehouse quality or finance. Preserve accepted/rejected/quarantine quantities, invoice source and exception evidence. Do not edit historical receipts, release held stock or pay an unmatched invoice. Resolving an exception does not rewrite the invoice match or quality disposition. Corrective posting and reversals need a future reviewed transaction workflow.

## Backup / restore drill to implement

Owner: operations. Stop writes and workers, capture consistent primary DB, private documents and integration-state evidence together, then restore into an isolated environment. Compare hashes and record counts, reconcile all external intents against the provider, verify one authorized read/write and one denial, and measure recovery time/data loss against approved RTO/RPO. This drill was NOT run. A database-only restore is insufficient when provider effects survive outside it.

## Release / rollback

Run backend tests and frontend build; inspect the requirement ledger. Use an immutable build identifier and preserve compatible schema, files and provider mappings. Rollback cannot erase a posted purchase or blindly replay outbox records. Model releases require a frozen evaluation report and expert approval; deployment/rollback automation is still required. The CI file is provided but was not executed in GitHub.

## Dependency outage or incident

Disable affected external execution, preserve audit/intent records and notify the assigned operational owner through your approved process. Model gateway failure must leave facts unchanged. Revoke affected credentials through the identity/integration owner, establish scope, fix the cause and reproduce failed tests before resuming. Do not paste credentials or confidential documents into public traces.

## Optional Docker path (unverified)

Set POSTGRES_PASSWORD, TOKEN_SECRET and DEMO_PASSWORD in your local environment or an uncommitted .env file. Use a URL-safe PostgreSQL password or correctly encode it in a separately configured DATABASE_URL. Run `docker compose build`, `docker compose up -d db redis`, `docker compose run --rm app python -m supplypilot.manage migrate`, `docker compose run --rm app python -m supplypilot.manage seed`, and `docker compose up -d app`. Add `--profile workers` only after testing the scanner/worker path and avoiding unintended manual worker races. Container volume ownership may need platform-specific initialization. Docker daemon access was unavailable during this delivery; these commands are not a successful deployment record.

Before dispatch the server rechecks authority, expiry, technical proof, evidence hashes, stock freshness and source revisions. A never-dispatched pending intent may be cancelled through Cancel pending; it releases its internal stock reservation and offer capacity and supersedes the old plan. Processing or uncertain intents cannot use this local cancellation: reconcile the provider first. This is not a posted ERP cancellation workflow.
