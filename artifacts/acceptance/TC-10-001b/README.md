# TC-10-001b acceptance evidence

The hardening run below is on `a866047fec1c1b31a4312681a8007408584651b9` (`a866047`). This README commit does not change that code.

`a866047` makes every recovery test in `test_job_leases.py` refuse to run when another eligible running job is present, and it deletes the rows `test_job_retries.py` commits. The suite list was run twice on that SHA. Both passes left `jobs.status = 'running'` at 0.

The earlier merge run was on `bc6a4dda1376b7de3bdbcaedec4bf946f481ecdd` (`bc6a4dd`).

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

## Hardening run

Both passes used the same commands, one suite after another, on `a866047`.

| What | Pass 1 | Pass 2 |
|---|---|---|
| Ruff check and format | passed | passed |
| `test_config_contract.py` | 627 passed | 627 passed |
| `test_job_leases.py` | 24 passed | 24 passed |
| `test_model_outcomes_threaded.py` | 1 passed | 1 passed |
| `test_safe_collection.py` | 29 passed | 29 passed |
| Heads / migration | 4 passed | 4 passed |
| `test_job_retries.py` | 70 passed | 70 passed |
| `test_job_idempotency.py` | 47 passed | 47 passed |
| `test_auto_generate_enqueue_conflict.py` | 5 passed | 5 passed |
| Running jobs left behind | 0 | 0 |

The four jobs that made the first `bc6a4dd` lease pass return 5 were left by `tests/release/test_job_retries.py`. Its `db` fixture committed and then only closed the session. The same four shapes were created again by the retries suite on `bc6a4dd` (ids 1080, 1083, 1107, 1109) after the earlier set (970, 973, 997, 999) had been classified:

| id | kind | how the test left it |
|---|---|---|
| 970, then 1080 | export, attempt 2, payload `questionnaire_id: 0` | `test_claim_increments_attempt_and_clears_schedule` claims the job and leaves it `running` |
| 973, then 1083 | export, attempt 10, `max_attempts` 50 | `test_claim_stops_at_ceiling_when_max_attempts_is_above_it` claims up to the ceiling and leaves it `running` |
| 997, then 1107 | generate_answers, attempt 2, `gen.xlsx` | `test_generate_transient_llm_errors_retry_only_failed_questions` sets attempt 2 and leaves it `running` |
| 999, then 1109 | generate_answers, attempt 1, `gen.xlsx` | `test_generate_bad_request_question_stays_visible_placeholder` runs generation and leaves the job `running` |

Those rows and their `gen.xlsx` questionnaires were deleted from `trustcopilot_test` before the two passes. Idempotency and TC-10-003d already delete rows above their watermark.

## Earlier merge run

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
