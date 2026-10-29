# Autonomous coordinator implementation plan

> Execution: owner requested autonomous completion; no further routine approval
> checkpoint. Use the existing repo and independent agent review.

**Goal:** Resume and advance the sale-readiness backlog without manual prompting.
**Architecture:** One scheduled coordinator, existing worker roles and GitHub CI;
a single operational state file provides a compare-and-swap lease and checkpoint.
**Spec:** `docs/release/CODEX_AUTONOMY.md` and the owner's 2026-10-30 instruction.

## Constraints and review focus

Preserve product scope and tests. No new service/dependency. Verify exact PR heads.
Avoid concurrent coordinators, stale leases, stale migration parents, false test
claims and repeated approvals for already-authorized engineering work.

## Tasks

- [x] Initialize `coordinator-state.json` on its own branch; verify an acquired
  lease round-trips through the GitHub connector. Keep bookkeeping out of master.
- [x] Independently review and merge #104 after verifying its four checks, so the
  existing planning package is available on master.
- [ ] Add root `AGENTS.md` and the run protocol; amend release-decisions.md to
  record the Codex coordinator's engineering/merge authority. Validate whitespace,
  secret scan, independent review, and normal push/PR CI before merging.
- [ ] Create one hourly task with durable repo links and explicit implementation,
  review and merge duties. Verify stored prompt, enabled status and cadence.
- [ ] Exercise the loop now against the existing queue. Record actual merges,
  checks and next actions; release the lease for scheduled continuation. Treat
  future scheduled execution as unverified until its run record exists.
