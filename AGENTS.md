# TrustCopilot engineering instructions

## Goal and authority

Finish the existing TrustCopilot sale-readiness backlog. On 2026-10-30 the owner
authorized Codex to operate the engineering workflow autonomously, including task
assignment, implementation, independent review, CI repair and merges. Routine
engineering work does not wait for owner approval or for the former Grok
coordinator. The Codex coordinator fills the Coordinator role in
`docs/acceptance/release-decisions.md`. Implementing workers do not self-merge,
except as owner decision OD-15 allows: the worker Grok may merge its own PRs once CI
is green on both events, except for account, authentication, authorization and
evidence-gate work (standing-queue groups 0 and 1). Acceptance always needs an
independent review, after the merge for self-merged PRs.

Read `docs/release/CODEX_AUTONOMY.md` for the run protocol and
`docs/release/PM_BACKLOG_PROTOCOL.md` for the shared progress workflow. **Grok PM
and Codex PM must use `docs/planning/backlog-state.json` and the human dashboard
at `docs/tracker/index.html`, updating them after each meaningful work batch.** A worker does this only
through the coordinator.
Original scope remains in `TrustCopilot_Execution_Backlog.json`; the tracker is
generated with `python scripts/backlog_tracker.py build` and checked with `check`.
Use the validated `update` command with the current revision; never hand-edit the
generated snapshot. Report accepted original-parent points / 1,864 only after
baseline verification; otherwise report the baseline as pending. PRs, children
and epic totals do not earn additional completion credit.

Agents without Jira access read the Jira backlog snapshot in
`docs/planning/jira/backlog.md` (planned assignments, due dates, sprints,
dependencies, and the text of post-freeze tickets); Jira stays the source of truth
for dates.

Issue #85 remains the live assignment and decision ledger. The coordinator lease
and merge gates below remain mandatory. `docs/release/CODEX_HANDOFF.md` and
`docs/planning/BACKLOG_STATUS.md` are historical starting points; current status
comes from the tracker reconciled with master, PRs and later rulings.

## Scope discipline

- Implement the assigned ticket's acceptance criteria using existing patterns.
- Preserve the current architecture, dependencies and product behavior unless
  the ticket requires a change. No speculative abstractions, rewrites, unrelated
  cleanup, added features, or dependency upgrades.
- Make the smallest complete change. Record any necessary technical ruling in
  #85 with its reason and affected ticket; do not silently change requirements.
- Never hide/remove features, relax acceptance, disable checks, or replace
  integration tests with mocks to make a task appear complete.
- Keep real-provider qualification distinct from mocked control-path coverage.
  Report actual test commands, tested commit, CI runs and remaining limitations.
- Existing owner decisions about money, accounts, rights and sale terms remain
  separate from engineering. Continue all independent work around those gates.

## Team and execution

The coordinator may delegate to up to three concurrent implementation workers
(backend, frontend, integrations/platform) plus an independent reviewer when
needed. Spawn workers only for executable, non-overlapping work. Use isolated
worktrees and exclusive file ownership, one ticket per PR, and no more than three
open PRs per worker. Review existing PRs before opening more. The coordinator alone
publishes shared-state changes and merges while holding the coordinator lease,
except worker self-merges under OD-15, which need no lease.

Workers return commits and evidence to the coordinator; they do not publish or
merge independently, except as OD-15 allows. Reclaim abandoned Grok work only after checking its live head
and recording the handover in #85. Preserve existing commits and attribution.

## Verification and merge

- Require independent review and resolve concrete blockers. PRs self-merged under
  OD-15 get this review after merge, before acceptance. Preference-only
  refactors are not merge blockers.
- Require `build` and `web-release-e2e` on BOTH push and pull_request for the exact
  final head. Do not count an older head's green run or an author's claim as proof.
- Squash-merge through GitHub, pinning the expected head SHA. Never push directly
  to master, force-push, rewrite history, or bypass repository protections.
- Serialize migrations; parent each on the actual landed Alembic head. Keep pure
  master merges, conflict fixes and migration re-parenting reviewable separately.
- After each merge, refresh master and dependencies, check master CI, and continue
  the next executable task. While master is failing, merge only an independently
  reviewed, exact-head-green repair PR (or, under OD-15, a worker's green pure revert
  of its own merge); verify master before unrelated merges.
  Do not wait for a human to say "continue."
- Run relevant local checks and the repository's required CI. Do not repeatedly
  rerun unchanged green work or create evidence-only commits that restart CI.

Follow the more specific `apps/web/AGENTS.md` when editing the frontend.
