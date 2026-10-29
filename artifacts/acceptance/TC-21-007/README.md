# TC-21-007: Reproducible framework coverage denominators

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text. There is no migration.

The unknown-reference check calls `_explain_control_inner` with a stand-in control. It does not set `session_replication_role` or disable triggers. Evidence owned by another workspace is linked with a real foreign key and is not counted.

The mapping hold-id change is outside this ticket. `test_domain_compliance_mappings.py` (TC-21-005) used to draw an id up to 2149999999, which overflows a signed integer. The span is now capped at 2140000000.

## Commands

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_coverage.py -q
python -m pytest tests/release/test_domain_compliance_mappings.py -q
```

Working directory `apps/web`. Node 24.

```text
npm run test:unit -- lib/coverageConsumer.test.ts
npm run typecheck
```

## SHA

Tests ran on `ac5c33cd455e796656e138e89f768ee6fae0ed05`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- Alembic head: `tc21005_mapping_version (head)`
- Master at the run: `6a26d60e44433720cf329cba08a8f096cb22e682`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_coverage.py -q` | 0 | 5 passed, 77 warnings, 2.43s |
| `python -m pytest tests/release/test_domain_compliance_mappings.py -q` | 0 | 10 passed, 185 warnings, 6.84s |
| `npm run test:unit -- lib/coverageConsumer.test.ts` | 0 | 4 passed |
| `npm run typecheck` | 0 | types generated, `tsc --noEmit` clean |

Pytest did not report a skipped test. The coverage progress line was `.....`. The mapping progress line was `..........`.
