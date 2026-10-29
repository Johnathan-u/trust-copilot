# TC-21-005: Versioned human-reviewed control mapping overrides

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_mappings.py -q
```

## SHA

Tests ran on `eb462fdf1c30c5937ae1e992696740f7038ecb6e`. This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic head after the test: `tc21005_mapping_version (head)`
- Migration parent: `bug018a_gap_closed_at_reason`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_mappings.py -q` | 0 | 6 passed, 124 warnings, 6.72s |

Pytest printed `6 passed, 124 warnings in 6.72s` and did not report a skipped test. The quiet progress line was `......`.
