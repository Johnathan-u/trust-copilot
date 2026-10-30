# Coordinator handoff to the Codex team

Written 2026-10-29 by TC Coordinator (Grok). Master at d9ab8b6.

## Purpose
The coordinator is running low on usage. This gives the Codex workers (backend, frontend, integrations) what they need to keep going. Issue #85 stays the ledger. Unless the owner (Johnathan-u) says otherwise, only the owner or the coordinator merges. If the coordinator goes quiet, keep working your queues and keep PRs green and ready. The owner can merge any PR that meets the checklist below.

Source of truth for remaining work: `docs/planning/` (the full planning package: 30 epics, 384 tickets) and `docs/planning/BACKLOG_STATUS.md`. Acceptance criteria are in the ticket docs under `docs/release/tickets` and `docs/planning/tickets`. Once your queue is empty, take the next free ticket from BACKLOG_STATUS (status backlog, with all dependencies merged). Claim it on #85 before you start.

## Merge checklist
- Squash merge pinned to the head sha, with all 4 checks green on that exact sha (build x2, web-release-e2e x2).
- Merge commits contain only conflict resolutions, verified with `git merge-tree`. Re-parents and other changes go in separate commits.
- Run update-branch only when files overlap.
- Migrations land one at a time and are re-parented onto master's head in a separate commit. Revision ids are 32 characters or fewer. Heads tests accept descendants. Downgrades are lossless and have a round-trip test.
- Tests clean up every row they create (including audit_events, notifications and idempotency rows) and assert counts. No trigger, FK or session_replication_role bypass.
- GETs are read-only. Missing and foreign ids return the same 404. No foreign workspace ids in responses.
- No ticket ids or env var names in OpenAPI or user-facing text. No internal ids in the UI.
- At most 3 open PRs per worker. Evidence records the tested code sha and the CI run id.
- No live provider calls. No new dependencies without a ruling. Never paste secrets. No history rewrite or secret rotation without the owner.

## Master and migration chain
The single head is `tc10001_job_leases` (... tc21006_gap_evaluation, then bug018b_gap_status_checks, then bug018c_one_open_gap, then tc10001_job_leases).

Landing order:
1. #73 (Platform, tc02001a), re-parented onto tc10001
2. TC-18-002 (#86) or TC-07-002 (#93), whichever is ready first
3. TC-18-001 (#88)
4. TC-17-004 (#91)
5. TC-23-001 (C&A, now #96)
6. TC-19-010 (#95)

## Open PRs (live state at 19:30 Copenhagen time)
| PR | Ticket | Owner | Head | State | What's left |
|---|---|---|---|---|---|
| #87 | TC-19-BUG-001 | Codex integrations | a7392b1 | ready, approved, 4/4 green | Squash-merge pinned to a7392b1. Follow-up PR: nested, unknown or empty encodings return invalid_encoding (outbound_http.py ~:57-59); the truncated-gzip test asserts invalid_encoding |
| #90 | TC-15-042 | Codex frontend | 7ad80ca | ready, 4/4 green (runs 40929352714 and 40929362187) | Re-review of the two fixes (3bfb234 docs, 7ad80ca wording). The AC1 framework-enable gap is accepted as rights-blocked |
| #86 | TC-18-002 | Codex backend | 8b5aa49 | draft | Finish; backend-only AC3 evidence, with the consumer under TC-15-024 |
| #88 | TC-18-001 | Codex backend | b57cb9b | draft | Finish; rebase onto the SMTP commit from #86 |
| #91 | TC-17-004 | Codex backend | 3ff0969 | draft | Finish the published-only public caller |
| #89 | TC-19-009 | Codex integrations | d633d65 | draft | Validation and access fixes |
| #95 | TC-19-010 | Codex integrations | 98e8781 | draft | Receipts table per ruling |
| #92 | TC-15-025 | Codex frontend | f16ca2c | open | Read-only partial; AC6 pending on TC-21-007b |
| #73 | TC-02-BUG-001a | Platform | d880ed9 | open | Re-parent, then merge (slot 1) |
| #83 | TC-21-013 | C&A | 96e7f89 | open | Round-2 blockers: decide/resolve race, gap_type over 64 chars gives a 500, scanner advisory lock 150016, create idempotency key bound to a body hash |
| #93 | TC-07-002 | Platform | 5d57216 | open | Re-parent when its slot comes up |
| #94 | TC-10-001a | Core | 50bbddb | open | Review |
| #96 | TC-23-001 | C&A | a392f93 | open | Waits for its migration slot |
| #75 | TC-14-008 | Web | 5705782 | open | Web fixes |
| #77 | TC-04-001b-web | Web | 177a878 | open | Web fixes |
| #5 | TC-20-001 | Integrations | 6fc2981 | blocked | — |

## Rulings in force
See #85 comments [6503678126](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6503678126), [6504557554](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6504557554), [6504620821](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6504620821) and [6504688809](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6504688809).
- TC-18-002 gets a minimal token final-submit endpoint; save/resume is TC-18-003. Tokens are hashed.
- SMTP sensitive=True goes in #86 as its own commit and never logs the body, subject or exception text. #88 rebases onto it.
- The public FAQ caller in security_page_service becomes published-only, inside #91.
- TC-19-009 keeps static templates; editable templates are TC-19-009a.
- The TC-19-010 receipts table is approved. A legacy NULL-user row counts as read if it has a receipt or legacy is_read is true. No backfill, and GETs never write.
- NotificationsPanel fixes are TC-19-010a (frontend), gated on #75.
- TC-15-042 may add one Sidebar entry after #75 merges.
- TC-15-025 decide/resolve actions are gated on #83. TC-15-024 waits for TC-18-002.
- The Back/workspace-switch unsaved-change guard is TC-14-014 (Web).
- AC6 provenance is TC-21-007b (C&A).
- No shared UI edits until #75 merges.

## Queues
| Worker | Queue |
|---|---|
| Backend | Finish #86, then #88, then #91 |
| Frontend | #90 re-review, then #92, then TC-19-010a and the Sidebar entry after #75, then TC-15-024 after TC-18-002 |
| Integrations | #87 merge, then #89, then #95, with the #87 follow-ups in a small PR |

## Owner-only decisions (log them; don't block on them)
Pricing; framework rights (TC-01-007); HRIS vendor; sandbox accounts; model spend cap; GA4 and domain; case-study consent; retention; signed ownership declaration; making the repo private; history rewrite; counsel review of TC-01-003 AC1; Slack opt-out behaviour; self-serve checkout; sales contact address; KMS for TC-07-002; sole-admin MFA recovery.

## Backlog follow-ups
TC-10-001a (Core, #94), TC-10-001b, TC-10-003e, TC-10-003g, TC-21-006a, TC-21-006b, TC-21-007a, TC-21-007b, TC-19-009a, TC-14-014, TC-02-OAPI-002, dropping the tc21005 hold tables, and Node 20 actions.
