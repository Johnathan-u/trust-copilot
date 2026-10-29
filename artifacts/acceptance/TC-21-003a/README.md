# TC-21-003a: Settle the accept-suggested idempotency claim after commit

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework control text and did not add a migration.

The file `tests/release/test_domain_compliance_controls.py` includes `test_accept_suggested_post_commit_failure_retries_without_duplicate` for both `tags` and `store`.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_controls.py -q
```

## SHA

Tests ran on `55d1fbd16a35563b855200358233c7626ab69430`. This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic head after the test: `tc21003_evidence_link_uniq (head)`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_controls.py -q` | 0 | 12 passed, 238 warnings, 9.63s |

Pytest printed `12 passed, 238 warnings in 9.63s` and did not report a skipped test. The quiet progress line was `............`.
