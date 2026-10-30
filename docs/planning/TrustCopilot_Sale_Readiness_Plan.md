# TrustCopilot full product handoff implementation plan

> **Current execution status:** use the [shared tracker](../tracker/index.html),
> [state ledger](backlog-state.json) and [Grok/Codex PM protocol](../release/PM_BACKLOG_PROTOCOL.md).
> This document and its initial NOT STARTED values preserve the original planning
> snapshot. The shared tracker records reconciled progress and evidence.

> For agentic workers: REQUIRED SUB-SKILL for later authorized implementation: `superpowers:subagent-driven-development` or `superpowers:executing-plans`. This request creates a backlog only. No source changes, public deployments, account changes, paid calls or issue publication have occurred.

**Goal:** Complete the entire existing TrustCopilot suite, polished user experience and traffic/product analytics, and prove that a buyer can independently install, operate and take it over.

**Architecture:** Keep Next.js web, FastAPI API, PostgreSQL/pgvector, private object storage and separate durable worker behind TLS. Repair the existing contracts and implement actual provider behavior; no framework rewrite is required.

**Tech stack:** Python/SQLAlchemy/Alembic, TypeScript/Next.js, Docker Compose, PostgreSQL/pgvector, S3-compatible storage, SMTP, configured model provider and buyer-owned integration/analytics accounts. Exact supported versions are locked during foundation work.

**Spec:** [PRODUCT_SPEC.md](PRODUCT_SPEC.md). **Repository:** https://github.com/Johnathan-u/trust-copilot · **Branch:** master · **Baseline:** `c20f949161ac12a619b396d30904448ffd74d532`. **Planning date:** 27 October 2026 Europe/Kiev.

## What to hand to an engineer

Hand over this entire directory/ZIP and repository access. Open `Backlog_Explorer.html` locally for search/filter/detail browsing; it uses no network, tracking, external scripts or server. Use this file as the execution guide and PRODUCT_SPEC.md as the scope/objective/behavior contract. Every ticket has its own Markdown file, point estimate, owner role, prerequisite IDs, source paths/API handlers, acceptance IDs, implementation checklist, test path/command and separate definition of done. `TrustCopilot_Execution_Backlog.json` is the canonical machine-readable backlog. No GitHub issues were created.

This version contains **30 epics, 384 mandatory tickets and 1864 provisional story points**. It replaces 54 broad work packages with reviewable delivery items. All 94 API modules, 489 statically declared route operations and 33 existing page files have explicit ticket ownership; additional management/public screens and missing provider actions are included. Runtime inventory is still required to catch dynamic mounts, timers and hidden entry points.

## Global constraints

- Full-suite scope is selected: no hidden feature exclusions or disabled mock modules counted as completed features.
- All tickets are NOT STARTED. Planned test paths are future files; this package does not assert new application runtime verification.
- Synthetic data and isolated environments only until separately authorized. Inspect application scripts before execution; never use discovered credentials or send customer evidence to model/analytics services.
- Public GA4 traffic, private first-party product events and operational telemetry are separate. No private content, credentials or bearer URLs go to Google Analytics.
- Every changed database structure has a migration/backfill/fresh-install/upgrade check. Every required provider has real authorized sandbox acceptance; mocks do not close that gate.
- Zero open confirmed critical/high exposures, corrupt supported workbook exports, unresolved core workflow defects or incompatible transfer rights at release.
- All numerical performance/quality/capacity/recovery values are proposed gates until measured, not existing product claims.
- P0/P1/P2 is priority, not scope. P2 polish/analytics remains mandatory for this full product request.

## Review focus

- Known foreign IDs, nested JSON references, direct object URLs and role changes must never bypass tenant authorization.
- Archived/deleted source support, reused answers and concurrent edits must never quietly turn into final approved exports.
- Crash/retry/cancel/provider-error races must preserve honest state and avoid duplicate records or unbounded charges.
- Every screen must handle errors, small viewports, keyboard access and unsaved changes; old screenshots and seeded responses are not evidence.
- Analytics must prove consent, safe payloads and real collection; synthetic traffic and stored event counters are not customers, revenue or historical audience.

## Epics and point totals

| Epic | Outcome | Tickets | Points |
| --- | --- | --- | --- |
| [E01](epics/E01.md) | Product scope and ownership | 6 | 21 |
| [E02](epics/E02.md) | Toolchain and continuous integration | 9 | 36 |
| [E03](epics/E03.md) | Deployment and migrations | 7 | 27 |
| [E04](epics/E04.md) | Accounts and sessions | 7 | 27 |
| [E05](epics/E05.md) | MFA SSO and role policies | 10 | 51 |
| [E06](epics/E06.md) | Tenant and object authorization | 6 | 39 |
| [E07](epics/E07.md) | Application and supply-chain security | 14 | 57 |
| [E08](epics/E08.md) | Evidence lifecycle and privacy | 11 | 48 |
| [E09](epics/E09.md) | Questionnaire intake and mapping | 8 | 40 |
| [E10](epics/E10.md) | Jobs storage and consistency | 7 | 34 |
| [E11](epics/E11.md) | AI grounding and citations | 9 | 42 |
| [E12](epics/E12.md) | Review approval and reusable knowledge | 14 | 68 |
| [E13](epics/E13.md) | Workbook and evidence exports | 7 | 32 |
| [E14](epics/E14.md) | Design system and accessibility | 13 | 52 |
| [E15](epics/E15.md) | Every screen and missing workflow UI | 67 | 334 |
| [E16](epics/E16.md) | Workspace administration audit and API usability | 6 | 24 |
| [E17](epics/E17.md) | Trust center public sharing and NDA | 10 | 51 |
| [E18](epics/E18.md) | Trust requests and vendor responses | 3 | 15 |
| [E19](epics/E19.md) | Slack Gmail and notification delivery | 10 | 56 |
| [E20](epics/E20.md) | Cloud directory code and CRM integrations | 54 | 275 |
| [E21](epics/E21.md) | Compliance controls mappings and gaps | 22 | 116 |
| [E22](epics/E22.md) | Monitoring alerts and remediation | 14 | 76 |
| [E23](epics/E23.md) | Deals contracts promises and proof | 8 | 52 |
| [E24](epics/E24.md) | Billing entitlements and credit ledger | 5 | 31 |
| [E25](epics/E25.md) | Product reporting and analytics | 11 | 55 |
| [E26](epics/E26.md) | Public traffic analytics and acquisition evidence | 19 | 77 |
| [E27](epics/E27.md) | Operations resilience and capacity | 9 | 40 |
| [E28](epics/E28.md) | Independent qualification and release gates | 6 | 39 |
| [E29](epics/E29.md) | Documentation demo and operating costs | 6 | 26 |
| [E30](epics/E30.md) | Asset transfer and buyer acceptance | 6 | 23 |


## Estimation policy and sequencing

Fibonacci scale 1/2/3/5/8 measures relative complexity, effort and uncertainty. These are initial planning estimates from static/code-audit evidence, not team-calibrated commitments. One point is not one hour/day. Do not convert 1864 points into a delivery date, valuation or sale probability. Re-estimate after clean-stack execution, provider/license discovery and first real-model evaluation. If a ticket exceeds the team's 8-point boundary, split it with traceable child IDs before sprint commitment. Do not double-count the earlier 54-package estimates or the research notes' illustrative UI points.

Suggested waves: 0: scope/rights/credential containment; 1: locked build/test infrastructure/migrations/identity; 2: authorization/security/evidence/queue contracts with design primitives in parallel; 3: grounded answers/review/export and usable core screens; 4: real full-suite provider/domain workflows plus their management screens and analytics; 5: combined security/model/browser/restore/capacity qualification; 6: documentation/demo/asset package and buyer takeover. Each ticket's exact dependencies govern start. Tests and documentation are delivered with every increment; qualification is independent confirmation, not postponed testing.

The first ready work is scope-contract, ip-provenance, safe-collection, secret-inventory and configuration/toolchain work as prerequisites permit. External account access, paid budgets, HRIS vendor selection, proprietary framework rights, branding/contact/region and contractual terms are owner decisions; record blockers and continue independent work. Do not guess those rights or silently drop the feature.

## Definition of ready and done

Every ticket embeds its own DoR/DoD. Common completion evidence: final SHA; actual commands/runtime versions; exit status and pass/fail/error/skip totals; fixtures and expected data; persisted DB/object/export assertions; screenshots/manual accessibility when UI changes; real provider/model evidence when promised; safe logs; documentation/config updates; reviewer approval. Documentation/legal/closing tickets use inventories, confirmed rights and independent runbook/acceptance evidence instead of meaningless unit tests.

Ticket acceptance IDs are stable `TC-01-001-AC1` style. A ticket is not DONE because its code exists, compiles, has a green toast or has a test with an impressive name. Allowed work states: NOT STARTED, READY, IN PROGRESS, IN REVIEW, BLOCKED, DONE. BLOCKED names owner, missing prerequisite and next action. All mandatory child tickets and epic integrated journeys must pass for epic completion.

## Release gates

| Gate | Required evidence |
|---|---|
| G0 Scope and rights path | Full scope, owner decisions, asset/license provenance and credential containment recorded |
| G1 Executable foundation | Locked fresh install, real pgvector/storage/worker stack, safe schema upgrade and functioning CI |
| G2 Security boundary | Current authority, all-surface tenant/role matrix, file/egress/proxy/session/key controls and independent retests |
| G3 Reliable core product | Fresh input→grounded answer→source review→approved faithful export with restart/job recovery |
| G4 Full suite and polish | Actual provider/domain workflows, all screens, privacy-safe analytics, accessibility/browser/model/security qualification |
| G5 Release and sale package | Measured capacity/cost/backup/restore, accurate docs/demo, final rights clearance, immutable artifacts/known issues |
| G6 Buyer takeover | Buyer accounts/new keys, independent install/workflow/update/restore, delivered rights/assets, seller access revoked and acceptance recorded |

Do not expose a public interactive demo before the relevant security, actual displayed-workflow and analytics/abuse gates pass. Full-product sale claims require all applicable gates, including every promised provider/catalog. No specific traffic threshold or invented user/revenue requirement is imposed on a pre-revenue asset; require accurate evidence, including zero traffic.

## Verification command conventions

Tests named in tickets do not yet exist. Toolchain tickets create the disposable test images/Compose overlay, marker configuration and generated credentials; actual commands are recorded by CI. Run `python -m pytest tests/release/test_<slug>.py -q` in the API test image, `npx playwright test e2e/release/<slug>.spec.ts` in the web test image, plus locked lint/type/build, full integration and broad browser suites on the release SHA. Manual evidence paths are explicit for rights/docs/closing tasks. All services use dedicated test DB/buckets/mail sandbox and deny unintended outbound traffic. No paid model/provider test starts without approved synthetic dataset and finite spend cap.

## Import and traceability

JSON has schema_version 2, epics and tickets. Import mapping: title→summary; id→external ID; epic→epic relation; story_points→story points; priority/status/owner_role→project fields; description+acceptance+DoD+interfaces+paths→issue body; depends_on→blocks/is-blocked-by. Map project-specific user IDs and workflow fields before any later authorized issue import. Tickets' Markdown bodies are ready for manual copy/import. This task has not written anything to GitHub/Jira/Linear.

`Traceability.json` and `TrustCopilot_Feature_Scope.md` map source surfaces to delivery and security tickets. `API_Contracts_At_Baseline.json` records declared handlers/request-field types without sensitive defaults. `TrustCopilot_Acceptance_Matrix.md` maps every ticket to acceptance/test/evidence. `AUDIT_COVERAGE.md` maps all 22 prior findings and 54 work packages. `research/` contains additional static evidence; its illustrative estimates are not additive. `PACKAGE_CHECKS.json` and `SHA256SUMS.json` verify document/package integrity, not application correctness.

The full feature suite is still unfinished today. This package tells a delivery team exactly what completion means and where to start; it does not validate $15,000, 30 days or any likelihood of sale.
