# Shared backlog protocol — Grok PM and Codex PM

Adopted for the owner's 2026-10-30 request for one information radiator for humans and AI.

## Read these sources at the start of every run

| Question | Authoritative source |
| --- | --- |
| What must the product deliver? | `docs/planning/TrustCopilot_Execution_Backlog.json`, `PRODUCT_SPEC.md`, acceptance decisions |
| What is the recorded execution and acceptance state? | `docs/planning/backlog-state.json` |
| What should a human open? | [Published tracker](https://johnathan-u.github.io/trust-copilot/docs/tracker/) or `docs/tracker/index.html` with its sibling CSS/JS/data files |
| How is the view produced and checked? | `scripts/backlog_tracker.py` |
| Who owns work and which decisions supersede earlier instructions? | Issue [#85](https://github.com/Johnathan-u/trust-copilot/issues/85), current coordinator lease and `AGENTS.md` |
| What proves delivery? | Actual commits, PRs, CI and ticket acceptance artifacts linked in the state |

The old `BACKLOG_STATUS.md` is a historical PR-title inventory. The old `Backlog_Explorer.html` points to the shared tracker. Neither supplies a competing current percentage. The initial planning snapshot's `NOT STARTED` labels describe its creation date.

Both PMs use the same state file and formula. Do not maintain separate Grok/Codex completion estimates. The dashboard is a committed snapshot, with a visible source SHA and observation time; it does not poll GitHub or prove a worker is running.

For scheduling, consult the generated `effective_depends_on`, `release_gate_dependencies` and `dependency_ruling_ids` fields and the cited `dependency_rulings`. They apply the existing [scope-freeze section 8 rulings](../acceptance/scope-freeze.md#8-coordinator-rulings-recorded-at-freeze) without changing the original planning contract. Original `depends_on` is retained as provenance. In particular, designated legal approvals gate release while engineering can proceed; transfer exceptions retain hard prerequisites. No engineering progress waives a release approval.

## What the dashboard reports

The frozen initial scope is 30 epics, 384 original tickets and 1,864 original points. The headline metric is **sale-readiness plan completion**:

`accepted original-parent points / 1,864 × 100`

A parent earns its original points once every original acceptance criterion and definition-of-done item has a recorded passing disposition, evidence and independent acceptance for the tested code. Merged PRs, child estimates and epic totals add no extra points.

Keep the headline **Baseline verification pending** until every original ticket has an explicit, complete baseline assessment. A missing assessment means unknown. Existing implementation and verified partial work must remain visible. Distinguish active PR work, known gaps, evidence awaiting reconciliation, blockers and unknown state.

Release gates and supplemental scope remain visible independently of this percentage. A 100% original-plan score does not waive licensing, accounts, security, operational or buyer acceptance gates. Scope changes require a versioned, reviewed migration and history; the ordinary update command rejects changes to the frozen source hash and denominator.

## One writer and one update per meaningful batch

The existing coordinator lease remains mandatory. Codex PM currently holds the coordinator role under the succession decision; Grok PM contributes through the current coordinator when it does not own that role. Workers must not race to update the shared ledger or self-merge.

1. Refresh master, the state revision, relevant issue #85 entries, actual PR heads and CI. Reconcile changes since the snapshot.
2. Claim executable work and exclusive files in #85, following the existing protocol.
3. Update affected ticket owner, state, blockers, next action, PR/evidence references and assessment as evidence changes. Record the actual observation time and tested source SHA.
4. Validate the update with the expected state revision, named actor and reason. A stale revision means reread and reconcile; never overwrite someone else's update.
5. Rebuild and check the display. Review state and generated-data diffs together.
6. Include the update in the relevant engineering PR or one deliberate batch reporting PR. Do not churn evidence-only commits that repeatedly restart unchanged checks.
7. Apply the existing independent-review, exact-head CI and merge rules. After merge, check master and correct any state invalidated by integration.
8. Add a concise #85 batch note linking the tracker and relevant commits, then checkpoint/release the lease when yielding.

A passing metadata validator proves that the record is structurally complete. The PM/reviewer must open and verify the evidence; a plausible URL or a claimed reviewer identity is not proof by itself.

## Commands

From the repository root:

```bash
python scripts/backlog_tracker.py summary
python scripts/backlog_tracker.py check
python -m unittest discover -s scripts/tests -p 'test_backlog_tracker.py'
```

Use the revision shown by `summary` when preparing a patch. For example, this patch changes only a next action, preserving the ticket's other fields:

```json
{
  "tickets": {
    "TC-09-002": {
      "next_action": "Verify the explicit answer-cell mapping against every original criterion."
    }
  }
}
```

Save the patch outside the tracked source tree, then run the following with the actual current revision and actor:

```bash
python scripts/backlog_tracker.py update --expected-revision 1 --actor codex-pm --reason "Clarify the next mapping verification step" --patch /tmp/backlog-patch.json
python scripts/backlog_tracker.py build
python scripts/backlog_tracker.py check
```

Grok PM uses its own actor identity when authorized to perform the same operation. No browser edit silently changes repository data. Human maintainers use this same CLI and PR workflow. Never hand-edit generated `docs/tracker/data.js`.

Patch fields are validated. Arrays and acceptance records must be supplied as complete replacements when updated; inspect the current state and the CLI help before changing them. For an acceptance decision, use all original criterion/DoD IDs, dispositions, evidence URLs, assessment metadata, tested SHA, implementer identities and an independent review record. The validator rejects missing evidence, self-review and unsupported states.

## Reporting format

Every progress report names the metric, scope version, accepted points/total points (or pending baseline), observation time/source SHA, change from the previous recorded snapshot, and open release gates. Reopened acceptance removes its points and remains visible in history. Never substitute a percentage of PRs merged, tests passed or files touched for accepted scope.

## Initial reconciliation

The initial state preserves the audited evidence at `b2bd1e0df5cdeb03b8d0cd240f5a161835ea621d`. It includes existing PR and acceptance-artifact references and known implementation gaps. None of these imports asserts a fully accepted original parent. Start by reconciling the high-risk known gaps and the most mature evidence-backed parents, retaining all working implementation.

The global PR registry and reconciliation queue retain their initial audit date and source SHA. A later state revision does not refresh those historical registries. Use each ticket's current recorded PR links, evidence and observation time for subsequent updates.

The CI timing repair and this tracker are bounded children of existing planning/control tickets. Their estimates are visible separately and do not change the original denominator.
