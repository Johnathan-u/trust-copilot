# TC-10-003c acceptance evidence

Branch `tc/core/TC-10-003c`, based on `origin/master` `a9ae7b370137ae5d3bb722bad2a5dbe6a1fddb00`.
Synthetic data only. The new tests use an in-memory object store and a local database whose name ends in `_test`. No network calls and no model calls.

`alembic heads` is one head: `tc21002a_canonical_uniq`. `bug019_article_slug_ws` is that head's parent. No migration in this change.

| File | What it shows |
| --- | --- |
| `regression_on_master_a9ae7b3.txt` | The new file against master's app code (`PYTHONPATH` on a checkout of `a9ae7b3`): **17 failed** |
| `focused_branch.txt` | The new file on this branch: **17 passed** |
| `focused_branch_repeated_5.txt` | The same file five times: **17 passed** each run |
| `safe_collection_guard.txt` | `tests/release/test_safe_collection.py`: **29 passed** |
| `full_suite_branch.txt` | Full `apps/api` suite on this branch, run at the same time as the master suite: **4 failed, 3019 passed, 11 skipped** |
| `full_suite_master_a9ae7b3.txt` | Full suite on master `a9ae7b3`: **3 failed, 3003 passed, 11 skipped** |
| `suite_comparison_by_test_id.txt` | JUnit comparison by test id |
| `alembic_heads.txt` | `tc21002a_canonical_uniq (head)` |

By test id, the branch adds 17 tests, all passing, and drops none. The only shared id whose result differed in the parallel full suites is `test_migration_upgrades_and_downgrades_on_a_fresh_database` (branch failed, master passed). That failure was `SSL connection has been closed unexpectedly` while both suites migrated fresh databases on one Postgres. Rerun alone, it passed. The billing migration test failed in both full suites under that same load and passed when rerun alone. The two failures that remain on both trees are environmental: the case-study consumer needs `apps/web` typescript installed, and the controls test rejects this environment's Node (`v22.23.4`).

Related suites in one run (guard, `test_job_idempotency`, `test_job_retries`, the new file, upload, parse, and export tests): **237 passed**.
