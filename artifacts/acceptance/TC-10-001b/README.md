# TC-10-001b acceptance evidence

These commands ran on merge `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` (`bc6a4dd`). This README commit does not change that code.

`bc6a4dd` is a pure merge of `origin/master` `80607881320e1fa2c6416c55730eb98a56449f26` (`8060788`) into `ee0389e`. Parents: `ee0389e8c399d0283def77b7d560a12022fb7a21` and `80607881320e1fa2c6416c55730eb98a56449f26`. The merge had no conflicts. Its diff against `ee0389e` is only the files those master commits changed.

This branch still adds no migration. The commits before the merge (`50af065`, `2ed5621`, `ee0389e`) do not touch `alembic/versions`. Master added `084_tc02001a_parent_workspace_move.py`, revision `tc02001a_parent_ws_move`, `down_revision = tc10001_job_leases`. `alembic heads` prints one head: `tc02001a_parent_ws_move`.

Base at branch cut was `b90a1e8de1c455bf27bdf09db4ebb2f71deb70f3` (`b90a1e8`). #94 is squash `da47b43` on that history.

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
| Ruff | `cd apps/api && ruff check . && ruff format --check .` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | check passed; format check passed |
| Alembic heads | `cd apps/api && alembic heads` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | `tc02001a_parent_ws_move (head)` |
| Config contract | `pytest tests/release/test_config_contract.py -q --tb=line` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | **627 passed** |
| Lease tests, including TC-10-001b | `pytest tests/release/test_job_leases.py -q --tb=line` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 on re-run | **24 passed** |
| Threaded model outcomes | `pytest tests/release/test_model_outcomes_threaded.py -q --tb=line` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | **1 passed** |
| Safe collection | `pytest tests/release/test_safe_collection.py -q --tb=line` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | **29 passed** |
| Heads / migration | `pytest tests/release/test_cross_workspace_refs.py::test_trigger_revision_is_on_the_single_alembic_head_chain tests/release/test_provider_adapter.py::test_migration_columns_present tests/release/test_provider_adapter.py::test_migration_has_unique_descriptive_revision_after_075 tests/release/test_job_retries.py::test_migration_downgrade_and_upgrade_roundtrip -q --tb=line` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | **4 passed** |
| Retries | `pytest tests/release/test_job_retries.py -q --tb=line` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | **70 passed** |
| Idempotency | `pytest tests/release/test_job_idempotency.py -q --tb=line` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | **47 passed** |
| TC-10-003d | `pytest tests/release/test_auto_generate_enqueue_conflict.py -q --tb=line` | `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` | 0 | **5 passed** |

Suites ran one after another. The test database was upgraded to `tc02001a_parent_ws_move` before the run, and `alembic_version` was still that revision after the last suite.

The first lease run returned 5 from `test_null_lease_older_than_the_grace_is_recovered_once` because four pre-existing expired jobs in `trustcopilot_test` were classified in the same call (23 passed, 1 failed). The re-run on the same SHA, after those rows were no longer running, was 24 passed.

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
