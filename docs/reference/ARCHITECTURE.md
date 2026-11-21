# Architecture and decision records

## ADR-001: modular monolith

React/TypeScript → FastAPI routes → domain services → SQLAlchemy/PostgreSQL or local SQLite. One application boundary is easier to verify than independent agent microservices at this stage. Static frontend files are served by the API after build. Celery/Redis is an optional outbox runner; manual dispatch is the locally verified path.

Modules: `security` verifies identity and roles; `domain` owns scope, audit and CAS; `procurement` owns business transitions; `planning` runs CP-SAT and an independent checker; `intelligence` owns a bounded extraction graph and transparent baselines; `integrations` isolates a durable external-state simulator. The graph has no purchasing authority.

## ADR-002: evidence and revisions

Private local document blobs are named by generated IDs, not uploaded paths. SHA-256, source pages and text offsets are persisted. Parsed text is untrusted and cannot change tools or policy. Local parsing is synchronous and bounded; a completed job record is persisted. This is not distributed OCR processing. Model gateway requests are opt-in and have quoted-source checks; suggested values remain unreviewed.

RFQ review records history and increments the revision. Plans freeze the current requirement, stock and offer revisions, full commercial payload and evidence hashes. Changes supersede unexecuted plans. Post-execution RFQ editing is blocked pending a future controlled amendment workflow.

## ADR-003: exact sourcing

Decision variables q[o] are nonnegative integer pieces and y[o] are Boolean offer selections. Hard constraints: sum q per SKU equals shortage; q ≤ capacity*y; q ≥ MOQ*y; q = pack_size*lot_count; technical eligibility; delivery by requirement date; quote validity; modeled total ≤ budget. Cost is sum(q*(unit price + per-piece freight) + y*fixed offer freight). Earliest-delivery scenario first minimizes quantity-weighted delivery ordinal, then cost within that best found delivery bound. Every accepted result reports feasible/optimal status and a bound. A non-optimal solve does not establish global optimality.

The checker independently recomputes source equality, quantities, pack/MOQ, capacity, dates, totals and budget. Small fixtures compare with exhaustive enumeration. Fixed freight applies per selected offer, not per consolidated supplier shipment. Currency conversion, weight/length conversion, service-level inventory and network planning are outside this model.

## ADR-004: controlled execution

Approval requires a distinct manager within configured authority. It binds the exact payload and expires. A buyer creates an intent and outbox entry in the same transaction as audit, internal inventory reservations and quoted-capacity consumption. Same tenant/key/payload returns the prior intent; a changed payload conflicts.

Worker claim is durable before the external call. A crash or timeout after a possible provider create is processing/uncertain, and requires reconciliation. The simulator stores its own durable unique key and external reference in a separate SQLite database. The simulation validates the algorithmic recovery path; it does not validate SAP, Oracle, Dynamics or another real provider's semantics. Real adapters must handle absent deduplication, partial posting and reconciliation races explicitly.

## ADR-005: relational migration remains open

Current SQL tables: users, records (typed JSON aggregates), audit, outbox, schema_version. Record identity is globally unique; queries require tenant and supplier relationship checks. CAS updates prevent lost aggregate writes; atomic transactions encompass dependent effects. This is a reference data model, with application-enforced relationships. Full normalized keys, tenant-composite foreign keys, immutable revision tables, database row policies and forward/downgrade migrations remain required. Baseline migrate uses `metadata.create_all`; it cannot evolve an existing table.

## State ownership

RFQ: draft → validated; plan: pending → approved/rejected/superseded → execution_pending → executed; intent: pending → processing → uncertain/confirmed; order: confirmed → part_received/received → closed. Receipt disposition and invoice match state are independent. Exceptions are open/resolved/reopened; richer triage/assignment/waiting states remain open work. ERP owns posted transaction truth once a real connector exists.

## Reference documentation

Implementation patterns were checked against [FastAPI authentication](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/), [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) and [SQLAlchemy session transactions](https://docs.sqlalchemy.org/en/20/orm/session_basics.html). These references describe tools and patterns; they do not certify this application.

Dispatch is a second authorization boundary: queued approval expiry, current manager authority, technical eligibility, source hashes and stock freshness are checked before claiming. Queued source edits are blocked. Only a never-dispatched intent can be locally cancelled with atomic reservation/capacity release; processing/uncertain outcomes require external reconciliation.
