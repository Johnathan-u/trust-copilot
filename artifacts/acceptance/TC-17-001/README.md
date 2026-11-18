# TC-17-001 gap 1: no null-workspace published article

Create stores the session workspace. A null, omitted, or different body `workspace_id` is 400 and inserts nothing. An anonymous read does not return a published row whose workspace is null. A public read that names a workspace does not return another workspace's article. Update cannot move the row or clear its workspace.

This note does not accept TC-17-001. No migration. The batch-7 files `pytest.txt` and `environment.txt` in this directory are the earlier API run from `docs/release/verification/TC-17-001.md`. They are not this change. No `ci-runs.md` in this change.

## Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. Product code was `e4b71d23` (master). The new test file was present. `trust_articles.py` was not yet changed.

```text
python -m pytest tests/release/test_domain_trust_articles.py -q --tb=line
```

- Python 3.12.3, pytest 9.1.1
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), pgvector 0.6.0
- Database `trustcopilot_test` on 127.0.0.1:5432

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 7 failed, 1 passed, 22 warnings, 1.84s |

The passing test was `test_normal_create_and_read_unchanged`. The seven failures are the gap: null and omitted `workspace_id` were stored and returned 200 with `workspace_id: null` and `published: 1`; a different workspace was 403 rather than 400; an anonymous get returned the null-workspace published row, including its content; an anonymous get that named workspace 1 returned workspace 2's published article; patch of `workspace_id` was ignored and returned 200; patch of a null-workspace row returned 200 and changed the title. Log: `failing-before.txt`.

## SHA

The route and the release test are `d2ca889bc8a1d03e4161011bd115143345babbde`. The commit that records this line does not change them.

## Green command

Same interpreter, after the route change.

```text
python -m pytest tests/release/test_domain_trust_articles.py -q --tb=short
python -m pytest tests/test_trust_articles_api.py -q --tb=short
```

## Environment

- Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), pgvector 0.6.0
- Database `trustcopilot_test` on 127.0.0.1:5432
- No live provider. The suite's network guard was on.

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_trust_articles.py -q --tb=short` | 0 | 8 passed, 18 warnings, 1.89s |
| `python -m pytest tests/test_trust_articles_api.py -q --tb=short` | 0 | 11 passed, 32 warnings, 2.13s |

Pytest did not report a skipped test. Log: `passing-after.txt`.

Before this change the same release file was 7 failed, 1 passed. After it, 8 passed. The existing API file stayed 11 passed.

The same tree also passed the neighbors that read or write trust articles: `tests/test_multi_tenant.py`, `tests/test_wave3_p23_p29_api.py::test_p29_editor_cannot_delete_trust_article`, `tests/release/test_trust_article_slug_workspace.py::test_two_workspaces_auto_publish_same_control`, `tests/release/test_body_reference_workspace_scope.py::test_global_trust_article_is_not_a_promise_source`, `tests/release/test_principal_contract.py`, `tests/release/test_session_validation.py`, and `tests/release/test_remember_policy.py`. Together with the two files above, that run was 271 passed. Those commands are not the named release command.

`ruff check app/api/routes/trust_articles.py tests/release/test_domain_trust_articles.py` exited 0.

## Records revision 34

CI run IDs for #301 are in `ci-runs.md`. This records gap 1 only. The parent is not accepted.
