# TC-21-002: Legacy and canonical control contract reconciliation

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework control text.

| AC | Result |
|---|---|
| AC1 Both routes agree on canonical ID, version, owner, lifecycle, and evidence | Met by `apps/api/tests/release/test_domain_controls.py`. Legacy and compliance payloads share one canonical object. A drifted stored lifecycle is reported, not rewritten, by GET. |
| AC2 Positive, negative, and partial-failure cases on PostgreSQL | Met by the same file. Edit is required to write. A workspace mismatch is 404. A foreign document and a foreign owner are rejected. A failed evidence mirror and a failed contract event stay retryable and do not insert a second row. |
| AC3 Public schema, UI consumer, and persisted outcome agree across retry | Met by the same file. The nested `canonical` object is `control-contract/v1`. Node 24 loads `apps/web/lib/controlContract.ts` and accepts the same block from either route. Retry returns the saved row. |

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_controls.py -q
```

## SHA

Tests ran on `d3145d20b53cc99481f3b6af03d8c5f15e2b25a7` (merge of `1c8456be724f66f7979a9e775ea7bc20c54a296e` with `origin/master` `58b8c879612ad21759805ab614fb2c4f59f39ada`). This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic 1.20.1
- Node 24.22.1 for the UI reader imported by the agreement test
- `alembic heads`: `tc21002_control_contract (head)`, parent `tc24001_stripe_webhook_events`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_controls.py -q` | 0 | 6 passed, 0 skipped, 63 warnings, 5.04s |

No test in that file was skipped.
