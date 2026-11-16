# TC-21-006c: per-control savepoint in control evaluation

`evaluate_control` caught a database error and then read the failed result in the same transaction. PostgreSQL had already aborted that transaction, so the failed-status read raised `InFailedSqlTransaction`, later controls were not scored, and the scan did not commit.

Each control now runs inside `db.begin_nested()`. The savepoint rolls back on error. The failed result is read after that rollback. The other controls are scored, their rows are written, and the scan commits. The violating insert does not remain.

This note does not accept TC-21-006 or TC-21-006c. No migration.

## Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. The new test was in the tree. The savepoint was not.

```text
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_domain_compliance_gaps.py::test_database_error_on_one_control_does_not_abort_the_scan -q --tb=short
```

Base `4cce018c2fca469e04eaf115832e6fd55b381159`. The product commit is `2c1507ac653c381a4574383dd3316aeb70259903`. The red run is the uncommitted test on that base, before the product commit.

- Python 3.12.3, pytest 9.1.1
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 1 failed, 10 warnings, 2.36s |

The failure is `InFailedSqlTransaction` from `_gap_row` while recording `failed` / `check_error`, after `NotNullViolation` on `evidence_gaps.workspace_id`. Teardown counts show `evidence_gaps` stayed `0`. Log: `failing-before.txt`.

## Green command

Same interpreter, database, and test. The savepoint is in the tree.

```text
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_domain_compliance_gaps.py::test_database_error_on_one_control_does_not_abort_the_scan -q --tb=short
```

## SHA

The green test and the module run below ran on `2c1507ac653c381a4574383dd3316aeb70259903`. This file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3, pytest 9.1.1
- Node v24.22.1 on `PATH` for the web-reader checks (`node --version` starts with `v24.`)
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`
- Alembic head: `question_cell_mapping (head)`

## Totals

| Command | Exit | Total |
|---|---|---|
| the green command above | 0 | 1 passed, 10 warnings, 1.27s |
| `python -m pytest tests/release/test_domain_compliance_gaps.py -q --tb=line` | 0 | 17 passed, 117 warnings, 7.27s |

Pytest did not report a skipped test. Logs: `passing-after.txt`, `pytest-q.txt`.
