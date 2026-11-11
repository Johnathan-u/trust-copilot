# TC-21-008: Scoped actionable compliance alerts

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Revision `tc21008_alert_records` is 21 characters. Its single `down_revision` is `tc02001a_parent_ws_move`.

Removing the body of `_lock_alert_writes` made `test_concurrent_scans_leave_one_active_alert` fail: `second scan did not wait on the alert lock`. That edit was reverted before the run below.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release -q --tb=line
```

Web, from `apps/web`:

```text
npx vitest run
npm run typecheck
```

## Environment

PostgreSQL via the test `DATABASE_URL`. Alembic head on this branch is `tc21008_alert_records`.

## SHA

Tests ran on `ebf37b733521c68a7c5b5e4bf8a8680552a60cbb`. That commit is the parent of this evidence commit. This commit only changes docs.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| `tests/release` | 0 | 1901 passed, 7438 warnings, 203.52s |
| `npx vitest run` | 0 | 178 passed |
| `npm run typecheck` in `apps/web` | 0 | `tsc --noEmit` completed |

`tests/release/test_openapi_ticket_ids.py` is included in the release total.
