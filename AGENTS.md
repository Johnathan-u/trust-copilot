# TrustCopilot engineering instructions

## Goal and authority

Finish the existing TrustCopilot sale-readiness backlog. On 2026-10-30 the owner
authorized Codex to operate the engineering workflow autonomously, including task
assignment, implementation, independent review, CI repair and merges. Routine
engineering work does not wait for owner approval or for the former Grok
coordinator. The Codex coordinator fills the Coordinator role in
`docs/acceptance/release-decisions.md`; implementing workers never self-merge.

Read `docs/release/CODEX_AUTONOMY.md` for the run protocol. Issue #85 is the live
assignment and decision ledger. `docs/release/CODEX_HANDOFF.md` and
`docs/planning/BACKLOG_STATUS.md` are dated starting points: reconcile them with
current master, PRs and later rulings before acting.

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
publishes shared-state changes and merges while holding the coordinator lease.

Workers return commits and evidence to the coordinator; they do not publish or
merge independently. Reclaim abandoned Grok work only after checking its live head
and recording the handover in #85. Preserve existing commits and attribution.

## Verification and merge

- Require independent review and resolve concrete blockers. Preference-only
  refactors are not merge blockers.
- Require `build` and `web-release-e2e` on BOTH push and pull_request for the exact
  final head. Do not count an older head's green run or an author's claim as proof.
- Squash-merge through GitHub, pinning the expected head SHA. Never push directly
  to master, force-push, rewrite history, or bypass repository protections.
- Serialize migrations; parent each on the actual landed Alembic head. Keep pure
  master merges, conflict fixes and migration re-parenting reviewable separately.
- After each merge, refresh master and dependencies, check master CI, and continue
  the next executable task. While master is failing, merge only an independently
  reviewed, exact-head-green repair PR; verify master before unrelated merges.
  Do not wait for a human to say "continue."
- Run relevant local checks and the repository's required CI. Do not repeatedly
  rerun unchanged green work or create evidence-only commits that restart CI.

Follow the more specific `apps/web/AGENTS.md` when editing the frontend.
