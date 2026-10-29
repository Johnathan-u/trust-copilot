# TC-23-001: Typed scoped deals, rooms, and questionnaire links

Local only. This branch was not pushed.

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Amounts in the tests are synthetic (`990001.23`, currency `XTS`).

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. Database `trustcopilot_test` on PostgreSQL 16.15.

```text
python -m pytest tests/release/test_domain_deals.py tests/test_deals.py tests/release/test_deal_questionnaire_link_scope.py tests/test_crm_connectors.py -q
```

Web, from `apps/web`, Node 24:

```text
npx vitest run lib/dealConsumer.test.ts
```

## SHA

Tests ran on `bd25b381ef68722652770187e1a2cbd7d14c2c4f`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| The four pytest files above | 0 | 62 passed, 312 warnings, 9.98s |
| `dealConsumer.test.ts` | 0 | 3 passed |

`test_domain_deals.py` contributes 21 of those pytest results (10 read routes, 5 write routes, and 6 other cases). Pytest did not report a skipped test.

## Migration

`tc23001_deal_types` revises `tc10001_job_leases`. The round trip in `test_amount_backfill_downgrade_and_upgrade_round_trip` downgrades to that parent, upgrades, downgrades, and upgrades again. An exact float stays `100000.00`. `1/3` is held as its original float text with the reason `float value is not exactly representable as numeric(18,2)`, restored on downgrade, and held again on re-upgrade.
