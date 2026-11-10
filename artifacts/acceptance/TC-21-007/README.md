# TC-21-007: Reproducible framework coverage denominators

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text. There is no migration. Product code is unchanged: `apps/api/app/services/compliance_coverage.py` and `apps/api/app/api/routes/compliance_coverage.py` match master.

This record does not accept the ticket. Independent review is still outstanding.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python` (Python 3.12.3).

```text
SESSION_SECRET=test-secret TC_REQUIRE_DB=1 python -m pytest tests/release/test_domain_compliance_coverage.py -q
```

`TC_REQUIRE_DB=1` was set. Pytest reported no skip. The progress line was `.......`.

## SHA

Implementation SHA `c9623436e9c8b2402349ca6642df6950b1497ac3` (master at the branch point). The service and the route are that commit. The tests in `apps/api/tests/release/test_domain_compliance_coverage.py` and this evidence were added together on top of it. The local run used that product code plus those tests.

`ac5c33cd455e796656e138e89f768ee6fae0ed05` is not reachable from master. `git cat-file` cannot see that object in this clone, and it is not an ancestor of `c962343`. `pytest-q.txt` in this directory is the older capture from that commit (5 passed). It is not this run.

## Environment

- Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, psycopg2 2.9.13
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`
- pgvector extension 0.6.0 (local apt package). These tests do not call vector operators.
- Alembic head: `tc17003_security_claims (head)`
- Linux 6.12.113+ x86_64
- Synthetic rows only

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_coverage.py -q` | 0 | 7 passed, 0 skipped, 108 warnings, 2.80s |

The two new cases are `test_deleted_document_stays_in_the_denominator` and `test_numerator_counts_each_qualified_control_once`. The other five tests in the file passed with them.

## Negative controls (not committed)

Both edits below were restored. `git diff` on `compliance_coverage.py` is empty.

- Skipping `if doc.deleted_at is not None: return "deleted_document"` made `test_deleted_document_stays_in_the_denominator` fail: `assert 'qualified' == 'gap'` (1 failed).
- Replacing `sorted(set(qualified))` with `sorted(qualified)` left `test_numerator_counts_each_qualified_control_once` green (1 passed). Each control is appended once, so `set()` does not change this fixture.
- Counting one qualified id per evidence link and dropping `set()` made that test fail: `qualified_control_ids` was `[2, 2, 3]` against `[2, 3]` (1 failed).

## CI

GitHub Actions run and job ids for `build` and `web-release-e2e`, on both `push` and `pull_request`, are recorded in `result.json` after those runs finish. They are not in this section yet.
