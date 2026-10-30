# Autonomous Codex coordinator

Owner authorization: 2026-10-30, "Ok lets do that and keep it fully auntinimous",
following the proposed coordinator/worker/review/merge loop. The adoption record
is in issue #85. This supersedes earlier session-only and Grok-only merge waits;
other product, acceptance and owner-domain rulings remain in force.

## Operating model

One scheduled coordinator resumes work hourly through the connected GitHub tools.
Each active run keeps working while executable tasks remain. The schedule is a
restart mechanism, not a promise of a continuously running process. Usage limits,
service availability and connection permissions still apply. A scheduled task's
existence is not evidence that a run executed successfully.

Use the existing repo, worktrees, PRs, test suites and issue #85. No new application
service, paid runner or orchestration dependency is required. The root AGENTS.md
defines scope and merge rules. Use existing available model settings; do not
launch idle workers or repeated full-repository scans.

## Single coordinator lease

Operational state lives in `coordinator-state.json` on the separate
`codex/coordinator-state` branch. Never merge that branch into master. It contains
`schema_version`, `lease_owner`, `lease_expires_at`, `updated_at`, `automation_id`,
`last_master_sha`, `checkpoint` and `blocked_items`. Times are UTC ISO 8601.

1. Fetch the state file and its current blob SHA using the GitHub connector.
2. If a different owner has an unexpired lease, exit without repo mutations or
   worker dispatch. Do not overwrite the lease because the owner appears idle.
3. Otherwise generate a unique run token. Claim a two-hour lease by updating the
   file with its fetched SHA (optimistic concurrency). A conflict means reread;
   never force the write. Fetch again and verify the token before continuing.
4. Refresh the lease before less than 30 minutes remain. Before every published
   change or merge, verify that the token still matches and the lease is valid.
   A lost or expired lease stops further publication; workers only edit locally.
5. Persist the checkpoint and release the lease on normal exit by clearing owner
   and expiry, using a fresh matching SHA. On interruption, its expiry permits
   recovery; the next run must reconcile live PRs and CI before resuming.

Only operational state commits on this branch use `[skip ci]`, because they are
bookkeeping, never application changes. Product and instruction PRs use normal CI.
If state is missing or unreadable, do not perform uncoordinated writes: report the
specific infrastructure blocker and continue read-only diagnosis.

## Each run

1. Read root instructions, release decisions, the latest relevant #85 entries,
   live master SHA, open PR heads and CI. Reuse known unchanged evidence. Do not
   infer a worker is running merely because its branch exists.
2. Reconcile checkpoint with actual merged commits. Correct stale dependency
   gates; prioritize ready PR reviews and fixes that unblock other work.
3. Claim executable tickets in #85 before editing, with owner, branch, base SHA,
   allowed files and acceptance checks. Transfer paused Grok assignments by a
   recorded handover after inspecting their current PRs; keep their existing
   changes. Do not run two writers on a branch or shared worktree.
4. Delegate up to three independent implementation tasks. Workers implement,
   test and return local commits. The coordinator publishes branches/PRs. Use a
   separate reviewer for each substantive PR; its findings must cite actual code.
5. Review, fix and merge according to AGENTS.md. Dependencies, migration order and
   independent review apply even when all CI is green. Only the coordinator
   merges. For coordinator-authored setup/repair changes, obtain a fresh reviewer
   before the coordinator merges. Refresh master and inspect its CI after each
   merge. If master is red, only an independently reviewed, exact-head-green repair
   PR may merge until master passes again.
6. Continue until the current run must yield, all remaining tasks have concrete
   gates, or release acceptance is complete. A blocked ticket does not block
   independent work. Record partial completion honestly; do not count it as Done.
7. Update #85 once per meaningful batch with merged PRs, exact heads/checks,
   assignments, blockers and next actions. Persist the checkpoint, release the
   lease, and let the next scheduled run resume. Avoid repetitive status comments.

## Existing decisions and interruptions

Engineering autonomy covers code, tests, docs, technical rulings, branch/PR
management and qualified merges. It does not silently authorize new purchases,
paid API spend, new provider accounts, production deployment, destructive data
operations, credential rotation, history rewrite, legal declarations or buyer
communications. Keep those existing owner gates in release-decisions.md; advance
all unaffected engineering without repeated permission questions.

Never work around a tool approval denial. Record the rejected operation and reason
and use a materially safer permitted alternative if one exists. If access or usage
prevents progress, report it accurately and checkpoint; do not claim work continues.

On completion, publish the acceptance evidence and unresolved owner-only items,
then disable the recurring task. Notify the owner for meaningful completed batches,
release completion, or an actionable blocker; stay quiet on unchanged checks.
