# Phase 1 release review — 26 November 2026

This is an isolated combined candidate for review and validation. It does not merge, close or retarget the original PRs, install code in development, apply a development migration or deploy a service.

## Source revisions

All six source PRs were open, unmerged and individually green when this candidate was prepared. Their inline review-comment lists were empty; that does not constitute an independent human approval.

| PR | Scope | Tested head | CI evidence |
| --- | --- | --- | --- |
| [#17](https://github.com/shah-hussain-bangash/SupplyPilot-AI/pull/17) | Demo and browser synchronization | `4d50c65755139e5a9f417f546d7229f02fd4aa21` | [Passed run](https://github.com/shah-hussain-bangash/SupplyPilot-AI/actions/runs/45332303083) |
| [#18](https://github.com/shah-hussain-bangash/SupplyPilot-AI/pull/18) | Document metadata and evidence reads | `64177c9d29e2a6f635e88dec75b79ec96973da41` | [Passed run](https://github.com/shah-hussain-bangash/SupplyPilot-AI/actions/runs/45392307669) |
| [#19](https://github.com/shah-hussain-bangash/SupplyPilot-AI/pull/19) | Document-job storage 0012 | `38d1ce39914b2711ee4d677fb0add52ac40ab081` | [Passed run](https://github.com/shah-hussain-bangash/SupplyPilot-AI/actions/runs/45553261793) |
| [#20](https://github.com/shah-hussain-bangash/SupplyPilot-AI/pull/20) | Document-job relational reads | `c4709119e527b86f9c55649391e45b6238415d55` | [Passed run](https://github.com/shah-hussain-bangash/SupplyPilot-AI/actions/runs/45562429581) |
| [#21](https://github.com/shah-hussain-bangash/SupplyPilot-AI/pull/21) | Customer-quote storage 0013 | `ea6dc3d44ceca18da990d7212352978124500dab` | [Passed run](https://github.com/shah-hussain-bangash/SupplyPilot-AI/actions/runs/45602180432) |
| [#22](https://github.com/shah-hussain-bangash/SupplyPilot-AI/pull/22) | Readable photographic portal | `b7ba64a2ca74e75a19612d2c19e9a047b3053f27` | [Passed run](https://github.com/shah-hussain-bangash/SupplyPilot-AI/actions/runs/45769953221) |

## Integration decisions

- Start from PR #22's head, which already includes the #19 → #20 → #21 → #22 dependency chain.
- Add PR #17's case-study reproduction notes and scoped evidence. Its browser revision-wait correction is already retained in the later browser helper; do not overwrite the expanded UI checks with an older helper.
- Compose PR #18's document metadata/evidence reads with #20's job reads. The resulting adapter exactly matches the installed, clone-tested document/job adapter. The evidence endpoint matches the installed document-read endpoint. Preserve the document-specific regression tests.
- Combine the document acceptance checks with job acceptance checks, retain the quote-aware plan-corruption probe, and choose document probes with at least one parsed page and no processing-job parent references. These constraints exercise missing projections without violating legitimate foreign keys.
- Keep every migration through 0013 unchanged. Reads/writes for commercial quotes retain their existing paths in this phase.

## Validation

- Local TypeScript and production frontend build: passed.
- Local combined backend suite: 174 tests, including three response/commit regression cases.
- Local fresh SQLite/Chromium workflow: 36 checks passed; all eighteen screens, full-width photographic headers, mobile layout, distinct approval authority, simulator reconciliation, receipts, invoice recheck, closed order, supplier scope and audit.
- See the draft candidate PR for the exact tested commit and final hosted PostgreSQL, concurrency and same-container restore evidence.

The historical 957-check claim in the case study remains linked to its original CI run and tested revision. It is not the combined candidate's check count. Synthetic results are not measured savings, real supplier certification or production readiness.

## Integration order after explicit authorization

Review #17 and #18 against main, then #19. Follow with #20, #21 and #22 in dependency order, checking each updated base and resolving document/job adapter and acceptance-probe overlaps using this validated composition. The candidate also contains the response/commit stability fix described below. If integrating the originals individually, include that focused fix before final validation. Alternatively, explicitly authorize integration of this combined candidate and reconcile the original PRs afterward. Do not integrate both strategies automatically.

## Operational gates

The development database is at 0013. On 26 November 2026, a private post-0013 backup and separate restore verification passed: all public table rows, columns, constraints, indexes, owners, RLS, functions, triggers and grants matched, and the closed AED 7,250 order was preserved. The development portal was stopped with operator authorization; the separate UI preview stayed running. Keep the backup and runtime files private. Database data and installed source were not changed by this release validation. Restarting the PostgreSQL portal requires the operator's existing database password.

The interactive UI preview uses separate synthetic SQLite data. It is not the PostgreSQL development installation. Live ERP, email and payments remain disconnected. Production rollout, production acceptance and live integrations belong to later phases.

## Release-blocking transaction timing defect

The combined review reproduced a defect in the existing API: request-scoped yield dependencies can send the success response before `get_db` commits. A subsequent refresh can therefore miss the newly queued execution, and deferred commit errors can occur after HTTP success has started. See the [FastAPI dependency lifecycle documentation](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope).

The candidate uses the same cached function-scoped database dependency in authentication and endpoints, so tenant binding and the shared transaction stay intact and commit completes before the response is sent. Three regression cases were demonstrated failing before the fix: success-before-commit, integrity failure after success, and operational failure after success. They pass with the fix, including source/audit rollback and correct 409/503 responses. No migration or business authority changes are required.

The disposable browser runner supports an explicit test-only commit delay. Candidate CI uses 250 ms to verify real UI refresh behavior against delayed persistence. It changes only the runner-owned synthetic SQLite process, not product configuration or the development database. All ordinary approval, reconciliation and isolation checks remain enabled.
