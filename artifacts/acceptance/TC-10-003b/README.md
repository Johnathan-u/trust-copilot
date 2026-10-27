# TC-10-003b acceptance evidence

Branch `tc/core/TC-10-003b`, based on `origin/master` ce4d861. That base includes TC-10-002 (#33), TC-24-001
(#23) and TC-02-BUG-015 (#36). All runs use the `tc-core-api-test` image against a throwaway Postgres +
pgvector container on an isolated Docker network. DB names end in `_test`, the data is synthetic, and no model
or network calls are made.

| File | What it shows |
| --- | --- |
| `release_tests_idempotency_retries_billing.txt` | `tests/release/test_job_idempotency.py`, `test_job_retries.py` and `test_billing_provider.py` on the branch: **147 passed** |
| `regression_on_master_ce4d861.txt` | The new tests run against master's app code: **9 failed, 1 passed**. Both route tests fail with the real `IntegrityError: UniqueViolation uq_jobs_queued_idempotency_key`, which is the 500 path. The owner-token tests fail because `idempotency.claim` does not exist on master. |
| `migration_roundtrip_postgres.txt` | Online `alembic` round trip `head -> tc24001_stripe_webhook_events -> head -> -1 -> head` with a column check at each step, plus offline `--sql` for upgrade and downgrade |
| `full_suite_branch.txt` | Collect-only OK, safe-collection guard OK (25 passed, 1 skipped), full suite **2087 passed, 6 failed, 24 skipped** |
| `full_suite_master_ce4d861.txt` | Baseline on master: **2078 passed, 6 failed, 24 skipped** |

The 6 failures are the same on master and the branch, and both are environmental. Four tests need the `node`
binary, and two (secret inventory) need the `git` binary. Neither binary is in the test image.

Branch minus master: +9 tests, all passing, and no new failures.
