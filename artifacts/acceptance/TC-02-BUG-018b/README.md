# TC-02-BUG-018b evidence

Synthetic rows only, on disposable side PostgreSQL databases whose names end in `_test`. No model calls and no network calls from the tests. Local Postgres 16 with pgvector. Ruff 0.5.6.

## This run

Results were produced on the code tree of commit `b6d65b72eafef88552ca27f45b7322f69f23d94b`.

That is the review-fix commit those commands checked out: 10 passed in `tests/release/test_evidence_gap_status_checks.py`, and 29 passed in `tests/release/test_safe_collection.py`. Writing this SHA into the README changes the branch head. The test module and the migration are the bytes from that commit. The same two commands were run again on the branch head after this paragraph was added; the counts were unchanged.

| Command | Result |
|---|---|
| `tests/release/test_evidence_gap_status_checks.py` | 10 passed |
| `tests/release/test_safe_collection.py` | 29 passed |

`logs/status-checks.txt` and `logs/safe-collection.txt` are that run. Afterwards, no `bug018b-synthetic` rows remained and `alembic_version` was `bug018b_gap_status_checks`. `logs/alembic-heads.txt` is `bug018b_gap_status_checks (head)`.

`origin/master` had not moved (`6a26d60e44433720cf329cba08a8f096cb22e682`), so this commit is not a merge. The migration parent is still master's head, `tc21005_mapping_version`.

The status-check file has 10 tests. Teardown still records `max(id)` and the row count for `evidence_gaps`, `questions`, `questionnaires`, `jobs`, `audit_events` and `workspaces`, deletes every higher id, and requires the counts to match. It does not call `setval`. The migration tests delete synthetic rows and then run `upgrade head`, with the upgrade in a `finally`.

`NOT VALID` then `VALIDATE CONSTRAINT` validates the checks against existing rows. `alembic/env.py` runs the migration in one transaction, so those steps do not shorten the lock.

## Earlier full-suite run

The logs below are from commit `a923730afb8843cb4ee5dfdd4941e708a62ee7a8`, when the status-check file had 9 tests. They are not the count for this commit.

| File | What it shows |
|---|---|
| `logs/round-trip.txt` | Downgrade drops both checks and leaves the synthetic row unchanged. Upgrade adds the checks back, validated, and the row is unchanged. |
| `logs/offline-sql-upgrade.txt` | Offline upgrade SQL. `NOT VALID`, then `VALIDATE CONSTRAINT`, for each check. No `evidence_gaps` data writes. |
| `logs/offline-sql-downgrade.txt` | Offline downgrade SQL. Drops the two constraints only. |
| `logs/offline-sql-upgrade-stderr.txt` | Alembic's offline-mode log lines for the upgrade SQL. |
| `logs/offline-sql-downgrade-stderr.txt` | Same for the downgrade SQL. |
| `logs/gap-tests-branch.txt` | Closure, regeneration, totals, safe-collection, and the 9 status-check tests then in the file: 72 passed. |
| `logs/regression-master.txt` | Those 9 tests copied onto master `6a26d60`: 7 failed, 2 passed. |
| `logs/full-suite-branch.txt` | Full `apps/api` suite on that commit: 3142 passed, 2 failed, 11 skipped. |
| `logs/full-suite-master.txt` | Full `apps/api` suite on master `6a26d60`: 3133 passed, 2 failed, 11 skipped. |
| `logs/suite-compare.txt` | Those two junit results compared by test id. 9 ids only on the branch. |
| `logs/ruff-check.txt` | `ruff check` on `apps/api` at that commit. |
| `logs/ruff-format.txt` | `ruff format --check` on the Python files changed then. |
| `logs/pre-commit.txt` | `pre-commit run --files` on those files. |

On master, `test_values_the_app_writes_are_accepted` and `test_non_resolved_row_may_keep_close_reason` passed because those values already fit the unconstrained columns. This commit adds `test_committed_gap_row_is_removed_after_the_test`, which also inserts a legal open gap. The rejection, pre-scan, round trip, offline SQL and heads tests still fail on master.
