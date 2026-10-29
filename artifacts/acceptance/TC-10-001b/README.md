# TC-10-001b acceptance evidence

These commands ran on `2ed56213b532f4706c4d00a4b68aa97d238180ca` (`2ed5621`). This README commit does not change that code.

`2ed5621` documents the grace recovery. The behavior is `50af065`. No migration. Alembic head stayed `tc10001_job_leases`.

Base at branch cut: `origin/master` `b90a1e8de1c455bf27bdf09db4ebb2f71deb70f3` (`b90a1e8`). #94 is squash `da47b43` on that history.

## Environment

- Python 3.12.3, pytest 9.1.1, ruff 0.5.6
- SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0
- PostgreSQL 16.15, database `trustcopilot_test` on `127.0.0.1` (name ends in `_test`)
- The new tests were also run against the worker at `origin/master` `b90a1e8` on that same database
- Synthetic rows only. No network calls from the tests, no real provider keys

## Design

No migration. `jobs.updated_at` and `jobs.started_at` already exist. The grace predicate is `COALESCE(updated_at, started_at) <= now() - grace` under `FOR UPDATE SKIP LOCKED`. An index was not added.

## Commands, exit status, totals

| What | Command | SHA | Exit | Totals |
|---|---|---|---|---|
| Ruff | `cd apps/api && ruff check . && ruff format --check .` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | check passed; 667 files already formatted |
| Alembic heads | `cd apps/api && alembic heads` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | `tc10001_job_leases (head)` |
| Config contract (generated doc, env scan) | `pytest tests/release/test_config_contract.py::test_contract_doc_is_generated_from_code tests/release/test_config_contract.py::test_every_env_var_read_by_the_api_is_in_the_contract -q --tb=line` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | **2 passed** |
| Lease tests, including TC-10-001b | `pytest tests/release/test_job_leases.py -q --tb=line` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | **24 passed** |
| Threaded model outcomes | `pytest tests/release/test_model_outcomes_threaded.py -q --tb=line` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | **1 passed** |
| Safe collection | `pytest tests/release/test_safe_collection.py -q --tb=line` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | **29 passed** |
| Heads / migration | `pytest tests/release/test_cross_workspace_refs.py::test_trigger_revision_is_on_the_single_alembic_head_chain tests/release/test_provider_adapter.py::test_migration_columns_present tests/release/test_provider_adapter.py::test_migration_has_unique_descriptive_revision_after_075 tests/release/test_job_retries.py::test_migration_downgrade_and_upgrade_roundtrip -q --tb=line` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | **4 passed** |
| Retries | `pytest tests/release/test_job_retries.py -q --tb=line` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | **70 passed** |
| Idempotency | `pytest tests/release/test_job_idempotency.py -q --tb=line` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | **47 passed** |
| TC-10-003d | `pytest tests/release/test_auto_generate_enqueue_conflict.py -q --tb=line` | `2ed56213b532f4706c4d00a4b68aa97d238180ca` | 0 | **5 passed** |

Suites ran one after another. After the last one, `alembic_version` was still `tc10001_job_leases`.

## What fails on master `b90a1e8`

The branch test file was copied onto a detached worktree of `b90a1e8` and these tests were run against that worker.

| Test | Result on `b90a1e8` |
|---|---|
| `test_null_lease_grace_defaults_and_clamps` | Failed. `null_lease_grace_seconds` is not on master. |
| `test_null_lease_older_than_the_grace_is_recovered_once` | Failed. `recover_abandoned_jobs` returned 0. |
| `test_null_lease_younger_than_the_grace_is_untouched` | Passed. Master also leaves a young NULL lease alone. |
| `test_null_lease_uses_started_at_when_updated_at_is_null` | Failed. Returned 0. The aged row was not recovered. |
| `test_two_recoverers_take_one_null_lease_job` | Failed. Both sessions returned 0, not `[0, 1]`. |
| `test_mixed_null_and_expired_leases_are_all_recovered` | Failed. Returned 1. Only the expired lease was recovered. |
