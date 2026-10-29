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
