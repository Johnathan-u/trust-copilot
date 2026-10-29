# TC-10-004 acceptance evidence

These commands ran on `77893bc6fe4833fb024611766d0a668514f91684` (`77893bc`). This README commit does not change that code.

`77893bc` deletes leaked login sessions, covers two concurrent manual retries, joins those threads in a finally block, rejects a cross-workspace cancel, and refuses a manual retry when another queued or running job already has the same idempotency key. Cancellation was run twice.

An earlier run on `78ddb03` is superseded by this one.

`78ddb03` removes the non-string status exception. An unexpected status is not running, so the write is skipped. The threaded worker test answers the status-fence query with `('running', None)`.

An earlier run on `b1f2125` is superseded by this one.

No migration. `cancelled` was already a `jobs.status` value, and the actor, prior error, and prior attempt are audit fields. Alembic head stayed `tc02001a_parent_ws_move`.

Base is `origin/master` `b70ba0faa94382b3ccd6b4dd807d0d23a692f354` (`b70ba0f`), the squash of #98. That commit was still the tip of master when these commands ran, so there was nothing new to merge.

## Environment

- Python 3.12.3, pytest 9.1.1, ruff 0.5.6
- SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0
- PostgreSQL 16.15, database `trustcopilot_test` on `127.0.0.1` (name ends in `_test`), session TimeZone `Etc/UTC`
- The new cancellation tests were also run against the worker and routes at `b70ba0f`
- Synthetic rows only. No network calls from the tests, no real provider keys

## Commands, exit status, totals

| What | SHA | Exit | Totals |
|---|---|---|---|
| Ruff check and format | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | passed |
| `test_config_contract.py` | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | **627 passed** |
| `test_job_cancellation.py` (run twice) | `77893bc6fe4833fb024611766d0a668514f91684` | 0, 0 | **15 passed**, **15 passed** |
| `test_job_leases.py` | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | **26 passed** |
| `test_model_outcomes_threaded.py` | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | **1 passed** |
| `test_safe_collection.py` | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | **29 passed** |
| Heads / migration | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | **4 passed** |
| `test_job_retries.py` | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | **70 passed** |
| `test_job_idempotency.py` | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | **47 passed** |
| `test_auto_generate_enqueue_conflict.py` | `77893bc6fe4833fb024611766d0a668514f91684` | 0 | **5 passed** |

Suites ran one after another.

## What fails on master `b70ba0f`

The branch test file was copied onto a detached worktree of `b70ba0f`. Ten tests failed. `test_manual_retry_of_another_workspace_is_not_found` passed on that copy because a missing route is also 404. A later assertion requires the body `Job not found`, which that missing route does not return (`Not Found`).

| Test | Result on `b70ba0f` |
|---|---|
| `test_cancel_queued_job_is_terminal_and_not_claimed` | 404, the route does not exist |
| `test_cancel_while_running_blocks_the_workers_late_completion` | `app.services.job_control` does not exist |
| `test_cancel_retrying_job_clears_the_schedule` | 404 |
| `test_cancel_racing_lease_recovery_stays_cancelled` | `app.services.job_control` does not exist |
| `test_repeat_cancel_does_not_write_a_second_audit` | 404 |
| `test_cancel_completed_job_is_a_conflict` | 404, not 409 |
| `test_manual_retry_records_the_actor_and_prior_attempt` | 404 |
| `test_manual_retry_by_a_non_admin_is_forbidden` | 404, not 403 |
| `test_manual_retry_of_another_workspace_is_not_found` | Passed on the first copy (generic 404). The body assertion fails on master |
| `test_manual_retry_of_a_queued_job_is_a_conflict` | 404, not 409 |
| `test_enqueue_after_cancel_does_not_resurrect_the_cancelled_job` | `app.services.job_control` does not exist |
