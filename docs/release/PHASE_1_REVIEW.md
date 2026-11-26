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
- Combine the document acceptance checks with job acceptance checks, retain the quote-aware plan-corruption probe, and choose document probes with no processing-job parent references. These constraints exercise missing projections without violating legitimate foreign keys.
- Keep every migration through 0013 unchanged. Reads/writes for commercial quotes retain their existing paths in this phase.

## Validation

- Local TypeScript and production frontend build: passed.
- Local combined backend suite: 171 tests passed.
- Local fresh SQLite/Chromium workflow: 36 checks passed; all eighteen screens, full-width photographic headers, mobile layout, distinct approval authority, simulator reconciliation, receipts, invoice recheck, closed order, supplier scope and audit.
- Combined hosted PostgreSQL, concurrency and same-container restore validation: pending; see the draft candidate PR for final evidence.

The historical 957-check claim in the case study remains linked to its original CI run and tested revision. It is not the combined candidate's check count. Synthetic results are not measured savings, real supplier certification or production readiness.

## Integration order after explicit authorization

Review #17 and #18 against main, then #19. Follow with #20, #21 and #22 in dependency order, checking each updated base and resolving document/job adapter and acceptance-probe overlaps using this validated composition. This candidate is validation evidence; do not merge it automatically alongside the originals. Choose the release strategy explicitly to avoid duplicate integration.

## Operational gates

The development database is reported at 0013. The last supplied successful private backup was taken before that upgrade at 0012; a post-0013 backup/restore verification has not yet been supplied. Record that checkpoint before a development installation or operational release. Keep private dumps and runtime files out of GitHub.

The interactive UI preview uses separate synthetic SQLite data. It is not the PostgreSQL development installation. Live ERP, email and payments remain disconnected. Production rollout, production acceptance and live integrations belong to later phases.
