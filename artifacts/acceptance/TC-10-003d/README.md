# TC-10-003d acceptance evidence

Branch `tc/core/TC-10-003d`. Cut from `c03d91a0510f2621cbd3c7c2de8fa62fdb541dd6`. `origin/master` then moved to `2a8b1dc319e7b80bfd5d75e8a3e6236bdd079800` and was merged in.
Synthetic data only. The new tests use the local database whose name ends in `_test`. No network calls and no model calls.

`alembic heads` after the latest merge of `origin/master` is one head, `tc21005_mapping_version` (TC-21-005). This branch adds no migration.

Option (a): the worker commits the parse-job completion before `maybe_auto_generate`. An `EnqueueConflictError` is logged and stored as `result.auto_generate = enqueue_conflict`. It does not fail the parse job and does not leave a generate row.

| File | What it shows |
| --- | --- |
| `regression_on_master_c03d91a.txt` | The new file against master's app code (`c03d91a`): **2 failed, 3 passed**. The conflict test has no `auto_generate` marker. The OpenAPI test still sees `QNR-01`, `QNR-13`, and `QNR-02`. |
| `focused_branch.txt` | The new file on this branch: **5 passed** |
| `focused_branch_repeated_5.txt` | The same file five times: **5 passed** each run |
| `safe_collection_guard.txt` | `tests/release/test_safe_collection.py`: **29 passed** |
| `related_suites.txt` | Guard, job idempotency, job retries, upload enqueue conflict, automate-everything, questionnaire parser, upload/parse review, and the new file: **183 passed** |
| `ruff_check.txt` / `ruff_format.txt` | ruff 0.5.6 check and format on the changed Python files |
| `precommit.txt` | pre-commit on the changed Python files |
| `full_suite_branch.txt` | Full `apps/api` suite on the merge of `2a8b1dc`: **2 failed, 3127 passed, 11 skipped** (3140 tests) |
| `full_suite_master_2a8b1dc.txt` | Full suite on master `2a8b1dc`: **2 failed, 3122 passed, 11 skipped** (3135 tests) |
| `suite_comparison_by_test_id.txt` | JUnit comparison by test id |
| `alembic_heads.txt` | `bug018a_gap_closed_at_reason (head)` |

By test id, the branch adds 5 tests, all passing, and drops none. No shared id changed result. The two failures on both trees are environmental: the case-study consumer needs `apps/web` typescript installed, and the controls test rejects this environment's Node (`v22.23.4`; `apps/web/.nvmrc` is 24.22.1). The two full suites ran one after the other on one Postgres. An earlier pair against `c03d91a` (before the merge) is not the comparison above.
