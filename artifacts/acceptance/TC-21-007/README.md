# TC-21-007: Reproducible framework coverage denominators

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text. There is no migration.

## Commands

```text
python -m pytest tests/release/test_domain_compliance_coverage.py -q
```

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
npm run test:unit -- lib/coverageConsumer.test.ts
```

Working directory `apps/web`. Node 24.

## SHA

Tests ran on `8ac53bb71ea790f5997d3427caa3b4a48cfb1671`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- Alembic head: `tc21005_mapping_version (head)`
- Master at the run: `6a26d60e44433720cf329cba08a8f096cb22e682`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_coverage.py -q` | 0 | 4 passed, 70 warnings, 2.08s |
| `npm run test:unit -- lib/coverageConsumer.test.ts` | 0 | 4 passed |

Pytest printed `4 passed, 70 warnings in 2.08s` and did not report a skipped test. The quiet progress line was `....`.
