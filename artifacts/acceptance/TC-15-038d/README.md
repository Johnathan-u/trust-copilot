# TC-15-038d publisher lock_timeout evidence

Local cloud VM, Linux x86_64. Python 3.12.3. pytest 9.1.1. SQLAlchemy 2.0.55. PostgreSQL 16.15 with pgvector. Interpreter `/tmp/tc-venv/bin/python`. The database is a local test cluster at `127.0.0.1:5432`, database `trustcopilot_test`, created by the API test fixtures (`alembic upgrade head`). No live provider was called.

`publish_running_progress` writes `{generated, total}` on its own short session with `SELECT ... FOR UPDATE`. Before this change that wait had no `lock_timeout`, so a job row already locked did not return. The publisher session now runs `SET LOCAL lock_timeout = '250ms'` in the same transaction. Postgres `55P03` (`lock_not_available`) is a skipped publish: the function returns `False` and leaves the row unchanged. Any other database error is still logged and returns `False`.

The named release test is `apps/api/tests/release/test_tc15038d_publisher_lock_timeout.py`. It locks the job row with `SELECT id FROM jobs WHERE id = :id FOR UPDATE` on another connection, then calls `publish_running_progress`. The call must return `False` within 1.5 seconds while that lock is still held, and the stored pair must stay `{generated: 0, total: 3}`. After the lock is released, the same row publishes `{generated: 1, total: 3}`. A second test publishes an unlocked row.

This note does not accept TC-15-038 or TC-15-038d. The child is not counted toward DONE.

## Failing before

Working directory `apps/api`. The new test was in the tree. `apps/api/app/worker.py` was the master publisher, with `FOR UPDATE` and no `lock_timeout`.

```sh
/tmp/tc-venv/bin/python -m pytest tests/release/test_tc15038d_publisher_lock_timeout.py -q --tb=short
```

Exit status 1. 1 failed, 1 passed, 2.67s. Log: [failing-before.txt](failing-before.txt).

`test_locked_job_row_skips_running_progress_quickly` was still running when the 1.5 second join ended. The unlocked publish passed.

## Passing after

Same interpreter. The publisher sets `SET LOCAL lock_timeout = '250ms'` and treats `55P03` as a skip.

```sh
/tmp/tc-venv/bin/python -m pytest tests/release/test_tc15038d_publisher_lock_timeout.py tests/test_job_progress_counters.py tests/release/test_job_progress_live.py -q --tb=short --durations=10
```

Exit status 0. 11 passed, 3 warnings, 1.53s. Log: [passing-after.txt](passing-after.txt).

The locked case's call duration was 0.35s, inside the 1.5 second bound. The other nine passes are the unlocked publish, the six TC-15-038c counter tests, and the two live parse/index progress tests.

## CI

`build` and `web-release-e2e` are green on push and pull_request for `2c1a357bdbc0d3564108ee860364b25f260f2bbe`. Run IDs are in [ci-runs.md](ci-runs.md). Pull request: https://github.com/Johnathan-u/trust-copilot/pull/285.
