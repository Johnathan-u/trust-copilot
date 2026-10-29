# TC-21-006: Explainable compliance gaps and review workflow

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text. Notification delivery was stubbed.

#78 (TC-02-BUG-018b) is not merged. Master is still `6a26d60e44433720cf329cba08a8f096cb22e682`, and its alembic head is `tc21005_mapping_version`. This branch does not widen `ck_evidence_gaps_close_reason`. Resolved control-check rows store `CONTROL_CHECK_CLOSE_REASON` (`evidence_sufficient`).

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_gaps.py -q
```

## SHA

Tests ran on `a4501822706ef88d40e74c9c3b913e5e76753239`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- Alembic head after the test: `tc21006_gap_evaluation (head)`
- Migration parent: `tc21005_mapping_version`
- Master at the run: `6a26d60e44433720cf329cba08a8f096cb22e682`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_gaps.py -q` | 0 | 8 passed, 56 warnings, 5.49s |

Pytest printed `8 passed, 56 warnings in 5.49s` and did not report a skipped test. The quiet progress line was `........`.
