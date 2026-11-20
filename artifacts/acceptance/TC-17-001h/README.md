# TC-17-001h: revoke acknowledgments with IS DISTINCT FROM

`revoke_acknowledgments` kept an acknowledgment whose `article_version_id` is null when another version was kept. SQL `!=` does not match null. The filter is now `IS DISTINCT FROM`, so that row is revoked. The kept version stays in force.

This note does not accept TC-17-001 or TC-17-001h. No migration. No `ci-runs.md`.

## Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. The new test was in the tree. `apps/api/app/services/trust_article_versions.py` still compared with `!=`. Base `2647b2e2ad5ef575ee354a3c9c92a8bd16680dbc`.

```text
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_domain_trust_articles.py::test_revoke_acknowledgments_revokes_a_null_version_id -q --tb=short
```

- Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), pgvector 0.6.0
- Database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 1 failed, 6 warnings, 1.63s |

`ack.revoked_at` stayed `None` (`tests/release/test_domain_trust_articles.py:682`). Log: `failing-before.txt`.

## Green command

Same interpreter, database, and test, after `is_distinct_from`.

```text
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_domain_trust_articles.py::test_revoke_acknowledgments_revokes_a_null_version_id -q --tb=short
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_domain_trust_articles.py -q --tb=short
```

## SHA

The service and the test are `6424a35df5e93d6aaa083399bd1428e27aab0fe8`. The green runs are that tree. This file was added after that commit and does not change them.

The behaviour comes from `bc2f2ed01b07b707a993e001203f8fa69d8d575e` on `fix/TC-17-001-remaining-gaps`. It was not in the #307 squash `7fea456d`. This branch ports the service filter and `test_revoke_acknowledgments_revokes_a_null_version_id` only.

## Environment

- Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, ruff 0.5.6
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), pgvector 0.6.0
- Database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`
- Alembic head: `tc05001c_mfa_satisfied`
- No live provider. The suite's network guard was on.

## Totals

| Command | Exit | Total |
|---|---|---|
| the single green command above | 0 | 1 passed, 6 warnings, 1.01s |
| `python -m pytest tests/release/test_domain_trust_articles.py -q --tb=short` | 0 | 15 passed, 69 warnings, 3.61s |
| `ruff check app/services/trust_article_versions.py tests/release/test_domain_trust_articles.py` | 0 | All checks passed |

Pytest did not report a skipped test. Logs: `passing-after.txt`, `pytest.txt`.
