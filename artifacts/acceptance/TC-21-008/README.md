# TC-21-008: Scoped actionable compliance alerts

Local only. This branch was not pushed. Framework catalogs stay **BLOCKED** pending **TC-01-007**.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_alerts.py -q
```

Web, from `apps/web`:

```text
npx vitest run lib/complianceAlertConsumer.test.ts
npm run typecheck
```

## Environment

PostgreSQL via the test `DATABASE_URL`. Alembic head after this revision is `tc21008_alert_records`, parent `tc02001a_parent_ws_move`.

## SHA

Tests ran on `28279672790b9144db3b05edb370538bb8ff4abe`. That commit is the parent of this evidence commit.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| `tests/release/test_domain_compliance_alerts.py` | 0 | 7 passed, 44 warnings, 4.86s |
| `complianceAlertConsumer.test.ts` | 0 | 3 passed |
| `npm run typecheck` in `apps/web` | 0 | `tsc --noEmit` completed |
