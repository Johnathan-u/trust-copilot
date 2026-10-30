# TC-01-006a — Shared backlog information radiator

Owner-requested child of TC-01-006, with a separate provisional estimate of 5 points. It does not add points to the original 1,864-point denominator or establish completion of the full parent.

## Delivered behavior

The static HTML/CSS/JavaScript dashboard exposes the complete original planning contract, current execution and acceptance records, epic rollups, blockers, engineering prerequisites, release gates, PR/evidence links, supplemental scope and revision history. The Python standard-library CLI validates and updates the shared ledger with optimistic revision checking, an atomic write and a local writer lock. The existing repository coordinator lease still governs cross-checkout publication.

Both Grok PM and Codex PM are directed to this source through `AGENTS.md`, `GROK.md`, `CODEX_AUTONOMY.md` and the shared `PM_BACKLOG_PROTOCOL.md`. Historical status documents have explicit notices; the old HTML explorer redirects to the tracker. Repository Pages already publishes the repository, so the dashboard uses that existing site without a new hosting service or configuration.

The canonical planning JSON remains byte-identical:

- 30 epics, 384 original tickets, 1,864 original points.
- SHA-256 `2ec27987ea9b4e3e89f88d409fc817aea22550cae2f2c10f6bd6e3c23190ff5a`.
- Every original ticket field is retained, including its historical status and dependencies.
- Scope-freeze R1–R4 are projected separately as effective engineering dependencies and release gates, with pinned source links. Transfer exceptions retain hard prerequisites.

The headline remains **Baseline pending** until every original parent has a complete assessment. Original-parent points are credited only after complete evidence and independent acceptance; child estimates, PR counts and partial implementations cannot inflate the numerator. Historical audit registries retain their own timestamp when current ticket state advances.

## Executed local checks

Integrated code head `53e073a3f5d3e00e69911ff28e0a7f5d7e85bef7`, tree `43863f9b16f1c431bb19460dd85b0bf0b65cadbb`, with ledger revision 2:

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s scripts/tests -p 'test_backlog_tracker.py' -v` | 20 passed, 45.589 seconds |
| `python3 scripts/backlog_tracker.py check` | Valid 384-ticket/1,864-point ledger; generated snapshot matches |
| Ruff 0.5.6 lint and format checks on builder and semantic tests | Passed; both files already formatted |
| `node --test docs/tracker/tests/browser.test.cjs` | 15 passed; zero failed, skipped or cancelled; 21.789 seconds |
| JavaScript syntax, full-diff whitespace and frozen-source hash checks | Passed |
| Desktop overview and 390-pixel mobile ticket inspection | No clipping or horizontal overflow; legible controls and complete scrollable detail |

Semantic tests exercise false/incomplete Done claims, evidence SHA matching, independent review, partial and complete baseline assessments, reopening and removal of credit, stale revisions, concurrent writers, canonical drift, malformed/future dates, generated-data drift, unsafe payload text and dependency rulings. Deterministic pending fixtures are independent of the live ledger. A separate consistency test and an advanced-baseline regression allow legitimate future status and acceptance changes without making CI depend on today's pending counts.

Browser checks exercise full-contract and path search, combined filters, deep links, keyboard focus restoration, mobile navigation, original/effective dependencies, supplemental legal gates, historical/current evidence separation, partial-assessment counting, `#main` initial navigation, safe text/URLs, JSON export, stale notices, offline loading and pending/verified progress display. Accepted browser fixtures exist only in memory; they do not create repository acceptance claims.

Local toolchain: Python 3.12.14, Node 24.22.1, Playwright 1.62.1 from the provided environment and Chrome for Testing 156.0.8078.80. The committed workflow uses Python 3.11 and the existing `apps/web` lockfile's Playwright 1.64.1. Local Chromium required permission for loopback IPC. No application dependency was added. Firefox and Safari were not tested locally.

## Independent review

Independent reviewer `/root/review_radiator` reviewed the implementation and data preservation, reproduced findings, and verified the corrections. Review covered the evidence-state invariant, full-contract search, accepted dependency rulings, immutable initial-audit dates, partial-assessment coverage, initial skip-link navigation and fixtures that tolerate future ledger progress.

At the integrated code head above, the reviewer reported no remaining Critical or Important issues after eight focused browser checks, the advanced-ledger regression, live-snapshot consistency, CLI validation, Ruff, JavaScript syntax and full-diff whitespace checks. The final published tree, small subsequent evidence/state changes and merge qualification are pinned in the PR and the coordinator's [issue #85 batch record](https://github.com/Johnathan-u/trust-copilot/issues/85).

## Repository CI and limits

The dedicated Backlog tracker workflow checks ledger semantics, deterministic generation and browser behavior on affected pushes and pull requests. Existing product `build` and `web-release-e2e` jobs remain required on both push and pull request for the exact final head. Their actual runs and post-merge master qualification are recorded by GitHub and linked in the coordinator ledger; this file does not predeclare an unpublished head green.

The pre-existing session-cookie timing failure was repaired separately in [PR #142](https://github.com/Johnathan-u/trust-copilot/pull/142), merged as `5e4093f3208b390855fb7bafbb4db3fdacad0adc`. It has its own independent review and acceptance evidence under TC-02-007c. The tracker includes a pure merge of actual master; it does not alter runtime application behavior.

This dashboard is a committed snapshot, not a live GitHub poller or browser editing service. External evidence still requires inspection: structural validation does not authenticate a reviewer or prove a URL's claims. Existing production-image, approval, provider, licensing/account and buyer gates remain in force. No original parent was marked Done by installing this tool.
