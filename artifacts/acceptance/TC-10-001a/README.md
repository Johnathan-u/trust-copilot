# TC-10-001a acceptance evidence

These commands ran on `0c618faa5cc208be295a25786e9e29c1143ca19d` (`0c618fa`). This README commit does not change that code.

Base is `origin/master` `a2458c9e2ae3c7b5f4cad7f293211afbb19e4687` (`a2458c9`), the squash of #84. Alembic head is `tc10001_job_leases`. This branch adds no migration.

## Environment

- Python 3.12.3, pytest 9.1.1, ruff 0.5.6
- SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0
- PostgreSQL 16.15, database `trustcopilot_test` on `127.0.0.1` (name ends in `_test`)
- The three new tests were also run against master's worker at `a2458c9` on that same database
- Synthetic rows only. No network calls from the tests, no real provider keys

## Commands, exit status, totals

| What | Command | SHA | Exit | Totals |
|---|---|---|---|---|
| Ruff | `cd apps/api && ruff check . && ruff format --check .` | `0c618faa5cc208be295a25786e9e29c1143ca19d` | 0 | check passed; format check passed |
| Alembic heads | `cd apps/api && alembic heads` | `0c618faa5cc208be295a25786e9e29c1143ca19d` | 0 | `tc10001_job_leases (head)` |
| TC-10-001 and TC-10-001a lease tests | `cd apps/api && SESSION_SECRET=test-secret TC_REQUIRE_DB=1 python -m pytest tests/release/test_job_leases.py -q --tb=line -p no:cacheprovider` | `0c618faa5cc208be295a25786e9e29c1143ca19d` | 0 | **18 passed** |
| Safe collection | `cd apps/api && SESSION_SECRET=test-secret TC_REQUIRE_DB=1 python -m pytest tests/release/test_safe_collection.py -q --tb=line -p no:cacheprovider` | `0c618faa5cc208be295a25786e9e29c1143ca19d` | 0 | **29 passed** |
| Heads / migration | `pytest tests/release/test_cross_workspace_refs.py::test_trigger_revision_is_on_the_single_alembic_head_chain tests/release/test_provider_adapter.py::test_migration_columns_present tests/release/test_provider_adapter.py::test_migration_has_unique_descriptive_revision_after_075 tests/release/test_job_retries.py::test_migration_downgrade_and_upgrade_roundtrip -q --tb=line` | `0c618faa5cc208be295a25786e9e29c1143ca19d` | 0 | **4 passed** |
| Retries | `pytest tests/release/test_job_retries.py -q --tb=line` | `0c618faa5cc208be295a25786e9e29c1143ca19d` | 0 | **70 passed** |
| Idempotency | `pytest tests/release/test_job_idempotency.py -q --tb=line` | `0c618faa5cc208be295a25786e9e29c1143ca19d` | 0 | **47 passed** |
| TC-10-003d | `pytest tests/release/test_auto_generate_enqueue_conflict.py -q --tb=line` | `0c618faa5cc208be295a25786e9e29c1143ca19d` | 0 | **5 passed** |

Suites ran one after another. After the last one, `alembic_version` was still `tc10001_job_leases`.

## What fails on master `a2458c9`

The branch test file was copied onto a detached worktree of `a2458c9` and these three tests were run against that worker. All three failed:

| Test | Result on `a2458c9` |
|---|---|
| `test_reclaim_after_classify_keeps_one_abandoned_audit` | Failed. `job.abandoned` count was 0. Classification committed, the reclaim landed, and the loop returned before the abandoned audit. |
| `test_one_conflict_in_a_batch_still_recovers_the_others` | Failed. The conflicted row had no `job.abandoned` audit. The log shows only two of the three expired jobs were classified; the `return` skipped the third. |
| `test_recovery_reraises_when_completed_status_query_fails` | Failed. `RuntimeError` was not raised. The status-query error was swallowed and the job was classified (`JOB_RETRY_SCHEDULED`). |
