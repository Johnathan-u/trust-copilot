# TC-10-005 acceptance evidence

These commands ran on `197846221258cddaa099b249e94b01c13ec8f116` (`1978462`). This README commit does not change that code.

`1978462` is a pure merge of `origin/master` `47b5972` (TC-21-007b, #99) into the branch. No conflicts.

No migration. `alembic heads` is one head, `tc02001a_parent_ws_move`.

## Environment

- Python 3.12.3, pytest 9.1.1, ruff 0.5.6
- SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0
- PostgreSQL 16.15, database `trustcopilot_test` on `127.0.0.1` (name ends in `_test`), session TimeZone `Etc/UTC`
- In-memory storage only. No network calls from the new tests, no real provider keys

## Commands, exit status, totals

Suites ran one after another from `apps/api`. Pytest used `SESSION_SECRET=test-secret` and `TC_REQUIRE_DB=1`.

| What | SHA | Exit | Totals |
|---|---|---|---|
| `test_enqueue_consistency.py` (first) | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **29 passed** |
| `test_enqueue_consistency.py` (second) | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **29 passed** |
| `test_job_cancellation.py` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **15 passed** |
| `test_job_leases.py` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **26 passed** |
| `test_model_outcomes_threaded.py` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **1 passed** |
| `test_safe_collection.py` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **29 passed** |
| `python -m alembic heads` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | `tc02001a_parent_ws_move (head)` |
| `test_job_retries.py` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **70 passed** |
| `test_job_idempotency.py` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **47 passed** |
| `test_auto_generate_enqueue_conflict.py` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **5 passed** |
| `test_config_contract.py` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | **627 passed** |
| `ruff check apps/api` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | passed |
| `ruff format --check apps/api` | `197846221258cddaa099b249e94b01c13ec8f116` | 0 | 677 files already formatted |

## What fails on master

The branch test file was copied onto a detached worktree of `78a8b3f` (the branch point; current master `47b5972` does not add this module either). Collection failed before any test ran.

`ModuleNotFoundError: No module named 'app.services.storage_reconcile'`

Exit 2. 1 collection error.

On that master the upload routes already roll the row back and best-effort delete the object when the commit or the enqueue raises. They do not sweep a failed delete, they do not keep the object when another row already uses that key, they do not re-queue a questionnaire that has no parse job, and a failed export commit leaves the object.

## Independent-review repair, 2026-10-30

Repair base: `68235eb3593593fd8bb4ceba6bfc24119d43b478` (PR #107).
The original commits above are preserved. No master integration is included in
this repair; that remains a separate merge and verification step.

The sweep and failed-commit cleanup now recognize deterministic output owned by
a queued/running export job, including fallback extensions. Point checks lock the
matching workspace/job row through deletion, so an inactive job cannot be retried
between the check and DELETE. The worker captures its attempt token before work,
confirms the existing lease immediately before PUT, and holds the same row through
the export-record commit. Rendering occurs before that lock. PUT exceptions roll
back immediately. The heartbeat only updates the same job row and does not wait
on handler work; it can wait behind this final section without a reverse lock
dependency. The existing SDK has finite connect/read timeouts and retry attempts;
no retry loop, storage API, dependency, migration, or key format was introduced.

Automatic recovery now respects cancellation of the current input. An older
recorded input does not block a new version; cancellation without a version is
preserved conservatively. Existing manual retry remains available. The idle-sweep
test uses a controlled monotonic clock, and upload-cleanup assertions follow the
new shared cleanup logger and message.

Local environment: Python 3.12.14, `/tmp/tc-backend-venv`, in-memory storage and
SQLite for deterministic query schedules. PostgreSQL is unavailable on this host.

| Check | Observed result |
| --- | --- |
| New stale-LIST/retry, stale-cleanup/winner, and cancellation tests before the repair | 7 failed for destructive deletes or unwanted recovery; 2 older-input cases passed |
| Active-output ownership/dry-run regression before the repair | 1 failed; active outputs were candidates |
| Deterministic SQL/storage regressions after the repair | 10 passed |
| Related enqueue consistency, upload cleanup, cancellation, lease, idempotency and retry suites | 61 passed, 159 skipped because PostgreSQL is unavailable |
| Changed-file Ruff lint and formatting checks | passed |
| `python -m alembic heads` | unchanged single head: `tc02001a_parent_ws_move` |
| `git diff --check` | passed |
| Full `python -m pytest -q` | interrupted with exit 130 at about 70%; showed failures/errors/skips; incomplete, no pass claimed |

The related-suite output is in `repair-local-targeted.txt`. The command was:

```sh
python -m pytest tests/release/test_enqueue_consistency.py tests/release/test_upload_enqueue_conflict.py tests/release/test_job_cancellation.py tests/release/test_job_leases.py tests/release/test_job_idempotency.py tests/release/test_job_retries.py -q
```

The PostgreSQL cases include cleanup versus manual retry for failed/cancelled/completed
jobs, lease takeover during PUT, stale-worker PUT refusal, and cancellation through
the real cancel/retry service. They remain unqualified locally and must run in CI.
An attempted SQLite stale-worker probe could not execute PostgreSQL's raw
`FOR UPDATE`; that scenario is therefore explicitly a PostgreSQL test, not an
emulated locking pass. Real object-store/provider qualification is not claimed.

Tested source blobs:

* `storage_reconcile.py`: `4211cfc893b5715dbc08039c2477e92093f72f3b`
* `worker.py`: `bc7eb2f2062be2b643ffa58dc45386fac4963e0d`
* `test_enqueue_consistency.py`: `eeb6b34fc7a20376eee13b91728f4100910bffd5`
* `test_upload_enqueue_conflict.py`: `40ae4919326891a6f3427ff216bd7ba7297b3381`

Fresh independent review, current-master integration, and exact-final-head CI
remain required before merge.
