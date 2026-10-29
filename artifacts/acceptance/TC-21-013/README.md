# TC-21-013: Evidence gap ownership and resolution

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Notification delivery was stubbed. There is no new migration. The pure merge of master `d9ab8b6` has tree equal to `git merge-tree --write-tree`. `alembic heads` is the single head `tc10001_job_leases`.

Create locks `pg_advisory_xact_lock(150015, questionnaire_id)` and `pg_advisory_xact_lock(150016, control_id)`. The scanner takes the same control lock before it inserts. A second open question gap hits `uq_evidence_gaps_one_open_per_question` and returns the existing row.

Decision and resolve use `UPDATE ... WHERE status = 'open' RETURNING`. The loser is 409, writes no audit row, and keeps no idempotency row. A decision that loses to resolve says `already resolved`.

A gap type longer than 64 characters, or a NUL byte in a string field, is 422. A create idempotency key stores `sha256` of the sorted JSON body in the existing payload. The same body replays. A different body is 422 and writes nothing.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release -q
```

## SHA

Tests ran on `94ab773f04b0be8ae66d73fa691ab13386f9d231`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| `pytest tests/release -q` | 0 | 1816 passed, 7177 warnings, 182.55s |

Pytest did not report a skipped test.
