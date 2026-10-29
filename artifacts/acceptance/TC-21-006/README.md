# TC-21-006: Explainable compliance gaps and review workflow

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text. Notification delivery was stubbed.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_gaps.py -q
```

## SHA

Tests ran on `309759b11e2f4c14a527468c5cc7cff00d588622`. This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic head after the test: `tc21006_gap_evaluation (head)`
- Migration parent: `tc21005_mapping_version`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_gaps.py -q` | 0 | 5 passed, 35 warnings, 4.57s |

Pytest printed `5 passed, 35 warnings in 4.57s` and did not report a skipped test. The quiet progress line was `.....`.
