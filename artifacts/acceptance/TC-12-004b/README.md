# TC-12-004b evidence

The named release test is `apps/api/tests/release/test_approval_regeneration.py`. The backlog command is `python -m pytest tests/release/test_approval_regeneration.py -q` from `apps/api`. This note does not accept TC-12-004 or TC-12-004b.

Product code is master `05ca009fbca03a0993997a429e5a697cf3879065`. That SHA already includes TC-12-004a (`ae4614caee2a0f0c25bb6410e4afef90efee095a`). This child does not change generation, regenerate, approve, export, or the review page.

## Red command

The file was not in the tree. Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_approval_regeneration.py -q --tb=short
```

| Command | Exit | Total |
|---|---|---|
| the red command above | 4 | file or directory not found; no tests ran |

Log: `failing-before.txt`.

## Green command

Same interpreter and the same product code, after the file in this commit was added. `TC_REQUIRE_DB=1`.

```text
python -m pytest tests/release/test_approval_regeneration.py -q --tb=short
```

| Command | Exit | Total |
|---|---|---|
| the green command above | 0 | 6 passed, 51 warnings, 1.25s |

Pytest did not report a skipped test. The warnings are `datetime.utcnow` in SQLAlchemy and in the existing generation and revision modules. Log: `passing-after.txt`.

The six cases are the cache hit, the uncached run, the explicit draft until reapproval, and the three refusals (no review permission, another workspace, a row that is not approved).

Environment: `environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0, database `trustcopilot_test`.

This folder does not record a CI run id. It does not accept TC-12-004 or TC-12-004b.
