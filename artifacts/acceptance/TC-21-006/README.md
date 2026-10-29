# TC-21-006: Explainable compliance gaps and review workflow

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text. Notification delivery was stubbed.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_gaps.py -q
```

## SHA

Tests ran on `794578efce9a7f58a484b8fdbac4c07873c4d208`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic head after the test: `tc21006_gap_evaluation (head)`
- Migration parent: `tc21005_mapping_version`
- Master at the run: `6a26d60e44433720cf329cba08a8f096cb22e682`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_gaps.py -q` | 0 | 7 passed, 50 warnings, 4.84s |

Pytest printed `7 passed, 50 warnings in 4.84s` and did not report a skipped test. The quiet progress line was `.......`.
