# TC-02-BUG-018 evidence

Synthetic rows only, on a disposable side PostgreSQL (`pgvector/pgvector:pg16`, internal Docker network, DB name ending `_test`). No model calls, no network access. Image `tc-core-api-test:c20f949-sa20-nopymupdf` (no `node`, no `git`). Branch = the fix merged with master `a702056`; single alembic head `tc10003b_idempotency_owner_token`; no migration.

| File | What it shows |
|---|---|
| `logs/gap-tests-branch.txt` | `tests/release/test_evidence_gap_generation.py`, `test_gap_totals_exclude_resolved.py` and the safe-collection guard on the branch: 49 passed, 1 skipped (21 gap tests, 28 + 1 guard). |
| `logs/gap-tests-master-a702056.txt` | The same two test files copied onto clean master `a702056`: 15 failed, 6 passed. |
| `logs/gap-tests-a00a5bf.txt` | The same two files against the first fix revision (`a00a5bf` service, model and totals services, on `58b8c87`): 10 failed, 11 passed. These are the ruling-driven tests. |
| `logs/gap-tests-ce4d861.txt` | Earlier evidence: the first five regeneration tests against `ce4d861` (TC-02-BUG-015). |
| `logs/service-tests.txt` | Affected service tests (benchmarks, export pack, executive dashboard, demo proof, compliance gaps, wave2 API, job idempotency/retries) on branch and master: 3 failed / 180 passed on both, the same three `node`-missing tests. |
| `logs/full-suite-summary.txt` | Full `apps/api` suite on master `a702056` and on the branch, with the safe-collection guard result. |

**What fails without the fix.**

- On master every regeneration test fails on behavior (`assert 'open' == 'resolved'`, or the stale gap stays open under concurrency); two existing tests fail only on the new `resolved` key in the return dict; the format test cannot import `append_resolution_note`.
- Against `a00a5bf`: the rejected and flagged tests fail because that revision closed the gap (`'resolved' != 'open'`); the sufficient and removed tests fail on the old `Resolved on regeneration: <code>.` suffix; the format test cannot import the helper.
- Each totals test fails on both: export pack lists resolved gaps, demo proof counts 4 instead of 2, benchmark and executive dashboard count 4 instead of 2, `gap_summary["total"]` is 4 instead of 2.

**Full suite.** Master `a702056`: 2276 collected, 2246 passed, 9 failed, 12 skipped, 10 errors. Branch: 2289 collected, 2259 passed, the identical 9 failed and 10 errors, 12 skipped. All failures and errors are environmental (`node`/`git` missing; installed packages differ from the dev lock). One earlier branch run also had an intermittent failure in `test_job_idempotency.py::test_replay_returns_same_error_body_as_live_response` (exports idempotent replay, unrelated to gaps); it passed on the rerun and 3/3 times alone. Details in `logs/full-suite-summary.txt`.
