# TC-10-001d acceptance evidence

Local run of the export-lease fix. The failing-before log is master's fence with the new tests applied. The passing-after log and the targeted run are this commit's tree. CI on the pull request is the PostgreSQL run that counts for the head SHA.

## Problem

An export locks the job row, uploads, then commits through the lease fence. The row lock blocks heartbeat renewal. After the fence started comparing `lease_expires_at` to `statement_timestamp()`, an upload longer than the remaining lease raised `LeaseLost`, discarded the upload, and left the job `running` for recovery to spend a retry. Recovery still skips locked rows, so the timestamp passing during the lock is not a takeover. No row was corrupted.

## Fix

`lease_is_held(..., lock=True)` is still the check `confirm_lease_for_commit` and the commit fence use. If this transaction already holds the job row, that call checks the owner token and sets `lease_expires_at` to `clock_timestamp()` plus the lease. A different token changes no row and still raises `LeaseLost`. If this transaction does not already hold the row, the check is unchanged: owner, `running`, and `lease_expires_at > statement_timestamp()` under `FOR UPDATE`.

The lock is detected by matching the tuple's `xmax` or `xmin` to a granted `transactionid` lock of this backend, including a subtransaction. The read does not take a new lock. Extending, rather than only skipping the expiry check, matters because the upload commit releases the lock. The later completion confirm would still see an expired lease if the timestamp had not been moved.

Heartbeat renewal uses `clock_timestamp()` instead of `now()`. A renewal that waits on the export's row lock no longer stores an expiry from the start of that wait.

The answer write guard is unchanged.

## Criterion → evidence

| Criterion | Evidence |
|---|---|
| An export upload longer than the lease fails on the old fence: `LeaseLost`, job stays `running`. | [`failing-before.txt`](failing-before.txt). Exit 1. `test_export_upload_longer_than_the_lease_commits` failed (`running` != `completed`). The log is `LeaseLost` from `fenced_commit` at `storage_reconcile.py` `session.commit()`. |
| The same upload commits the artifact, uses no retry, and does not raise `LeaseLost`. | [`passing-after.txt`](passing-after.txt). Exit 0. Worker lease patched to 2s, upload sleeps 4s. Job `completed`, attempt stays 1, export bytes stored. |
| A different token, including one another worker has taken, still raises `LeaseLost` at commit. A row lock does not keep a different token. | [`passing-after.txt`](passing-after.txt). `test_taken_over_lease_is_still_lost_at_commit` and `test_locked_row_still_rejects_a_different_token` passed both before and after the fix. |
| Existing lease, heartbeat, fence, and reconcile tests still pass, including the no-heartbeat control. | [`targeted-tests.txt`](targeted-tests.txt). Exit 0. 77 passed, 0 failed, 0 skipped. |

## Commands

From `apps/api`, with `SESSION_SECRET=test-secret` and `TRUST_COPILOT_TESTING=1`. Interpreter: `/tmp/tc-venv/bin/python` (Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, psycopg2 2.9.13). PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), pgvector 0.6.0, database `trustcopilot_test` on 127.0.0.1, Linux 6.12.113+ x86_64. This is the distro server, not the CI `pgvector/pgvector:pg16` image. The new tests use `clock_timestamp()`, `statement_timestamp()`, and `pg_locks`, which that image also provides.

Failing before, master's `job_lease.py`:

```
python -m pytest tests/release/test_job_leases.py::test_export_upload_longer_than_the_lease_commits tests/release/test_job_leases.py::test_taken_over_lease_is_still_lost_at_commit tests/release/test_job_leases.py::test_locked_row_still_rejects_a_different_token -vv --tb=short -p no:cacheprovider
```

Passing after:

```
python -m pytest tests/release/test_job_leases.py::test_export_upload_longer_than_the_lease_commits tests/release/test_job_leases.py::test_taken_over_lease_is_still_lost_at_commit tests/release/test_job_leases.py::test_locked_row_still_rejects_a_different_token -vv --tb=short -p no:cacheprovider
```

Targeted:

```
python -m pytest tests/release/test_job_leases.py tests/release/test_enqueue_consistency.py tests/release/test_job_idempotency.py::test_lease_heartbeat_renews_while_answer_batch_is_open -q --tb=line -p no:cacheprovider
```

Exit 0. 77 passed, 71 warnings, 23.13s. `ruff check app/core/job_lease.py tests/release/test_job_leases.py` reported no findings. The full API suite was not run locally. CI `pytest -rs` is the 6436-plus-these-tests run.

## Out of scope

On the failing commit, discard refused to delete the uploaded object because the export job was still `running`. `storage_key_is_referenced` treats an active export as protecting its deterministic key before the record commits. That object is left for the sweep. This change does not alter that rule. The fixed path commits the record, so the object is referenced on purpose.
