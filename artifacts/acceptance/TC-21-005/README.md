# TC-21-005: Versioned human-reviewed control mapping overrides

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_mappings.py -q
```

## SHA

Tests ran on `080f0752c232de04a020df2916a23bfdfbb3d804`. This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic head after the test: `tc21005_mapping_version (head)`
- Migration parent: `bug018a_gap_closed_at_reason`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_mappings.py -q` | 0 | 10 passed, 185 warnings, 8.08s |

Pytest printed `10 passed, 185 warnings in 8.08s` and did not report a skipped test. The quiet progress line was `..........`.
