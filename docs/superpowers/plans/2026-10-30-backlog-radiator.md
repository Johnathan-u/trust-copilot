# Backlog Information Radiator Implementation Plan

> **For agentic workers:** Execute the scoped tasks below in isolated ownership areas; coordinator integrates and obtains independent review.

**Goal:** One useful repository backlog for humans, Grok PM and Codex PM with verifiable progress.

**Architecture:** Canonical planning JSON plus a versioned state ledger feed a generated static dashboard. No application service or external dependency is added.

**Tech Stack:** HTML, CSS, browser JavaScript, Python standard library, existing GitHub CI.

**Spec:** docs/superpowers/specs/2026-10-30-backlog-radiator-design.md

## Global Constraints
- Preserve 30 epics, 384 original tickets and 1,864 original points.
- Keep baseline percentage unknown until verified, with binary full-parent acceptance.
- Preserve original acceptance contracts and existing merge/lease rules.
- No new dependency, paid service, provider calls or production deployment.
- Exclusive implementation ownership; coordinator alone commits/publishes shared state.

## Review Focus
- Complete contract preservation and dependency/child accounting.
- Missing or false acceptance evidence, self-review, source/scope drift and stale updates.
- Search/filter/deep-link correctness for the full real dataset.
- Stored-text/URL safety and offline/mobile/keyboard behavior.
- PM instructions cannot leave a competing stale progress source.

## Tasks
- [x] Data worker: write failing semantic tests, then state/builder/update/validator/summary and focused workflow; seed from prior audit and preserved canonical source. Own scripts/backlog_tracker.py, scripts/tests/test_backlog_tracker.py, docs/planning/backlog-state.json and generated docs/tracker/data.js.
- [x] UI worker: implement docs/tracker/index.html, styles.css and app.js against the design contract; provide focused browser validation. Own these files only.
- [x] Coordinator: add shared PM guide, root/planning/old-handoff pointers and child ticket; preserve original historical content with explicit supersession.
- [x] Independently diagnose existing session-duration CI failure in a separate worktree. Repair only if the cause and exact deterministic test intent are proved; separate review and PR.
- [x] Coordinator: integrate and run data semantics, snapshot consistency, security/format checks and browser checks. Inspect rendered desktop/mobile.
- [ ] Independent reviewer: inspect full diff and evidence; fix material findings, then publish scoped PR.
- [ ] Coordinator: required exact-head build/web on push/PR, qualified CI repair first if needed; squash merge pinned head, verify master, update #85 and release lease.

## Execution notes
2026-10-30: user requested direct implementation. Coordinator lease acquired; initial master b2bd1e0 has existing red session expiry assertion. Product work outside the tracker remains assigned as before.

2026-10-30: complete implementation and review corrections integrated. Twenty semantic tests and fifteen browser checks pass. Known blockers and two bounded children were recorded through revisioned updates. Separate repair PR #142 passed all four exact-head jobs and merged as 5e4093f; master qualification precedes the tracker merge. Remaining publication and final merge evidence is recorded in the PR and issue #85 to avoid evidence-only CI restarts.
