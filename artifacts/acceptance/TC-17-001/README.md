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

## Remaining gaps: version, acknowledgment, retry

This section is the re-check after gap 1. It does not replace the gap 1 logs above. No `ci-runs.md` update in this change. The parent is not accepted. DoD5 is the reviewer's step.

**Migration.** `apps/api/alembic/versions/tc17001_article_versions.py` (`tc17001_article_versions`, parent `tc04005a_member_revoked_at`) creates `trust_article_versions`, an immutability trigger, `trust_articles.published_version_id`, and `policy_acknowledgments.article_version_id`, `workspace_id`, and `revoked_at`. Review it before apply.

### Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. The new tests were present. The route, model, and migration were not.

```text
python -m pytest tests/release/test_domain_trust_articles.py -q --tb=line
```

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 5 failed, 8 passed, 30 warnings, 3.74s |

The eight passing tests are the gap 1 file. The five failures are the remaining gaps: no `published_version`, no `published_version_id`, a second create with the same key was 400 `already exists`, `app.services.trust_article_versions` was missing, and `article_version_id` was not a column. Log: `remaining-failing-before.txt`.

### Green command

Same interpreter, after the route, migration, and tests.

```text
python -m pytest tests/release/test_domain_trust_articles.py -q --tb=short
```

### Environment

- Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), pgvector 0.6.0
- Database `trustcopilot_test` on 127.0.0.1:5432
- No live provider. The suite's network guard was on.

### Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_trust_articles.py -q --tb=short` | 0 | 13 passed, 63 warnings, 2.48s |
| `python -m pytest tests/test_trust_articles_api.py tests/test_trust_center_publish.py tests/release/test_trust_article_slug_workspace.py tests/test_multi_tenant.py tests/test_wave3_p23_p29_api.py::test_p29_editor_cannot_delete_trust_article -q --tb=line` | 0 | 40 passed, 114 warnings, 6.48s |

Pytest did not report a skipped test on the release command. Log: `remaining-passing-after.txt`.

Before this change the release file was 5 failed, 8 passed. After it, 13 passed.

The route, migration, release test, and dashboard change through the versioned-publish work are `f42014b3bbec3430a7d340f15acdeded4ae68804`. That is not the head after the #307 review. The review fixes (first-upgrade bind, acknowledge the shown version, and the legacy-acknowledgment test) are the later commit named in the review section below.

## Review of #307

Claude requested changes on #307. The first upgrade was skipping the bind of existing acknowledgments, so every legacy row was revoked. That update now runs on every upgrade, before the revoke of rows that still have no version. `test_first_upgrade_binds_a_legacy_acknowledgment_without_revoking_it` downgrades to `tc04005a_member_revoked_at`, drops the `tc17001_*` archives, inserts a legacy acknowledgment, upgrades, and checks version 1 with `revoked_at` null.

Acknowledge now requires `article_version_id`. A stale id is 409. The current published id is 200. The dashboard sends the published version it is showing.

The code SHA for those fixes is filled in after the commit that contains them.

`npm run test:unit` in `apps/web` on that tree, Node 24.22.1: 60 files, 551 passed. `npm run typecheck` exited 0.

`ruff check` on the touched Python files exited 0.

### Migration roundtrip

From `apps/api`, `DATABASE_URL` pointed at `trustcopilot_test`, `TRUST_COPILOT_TESTING=1`.

A synthetic published article, version id 19, title `Keep`, content `v1`, and an acknowledgment bound to that version and workspace 1 were inserted. `alembic downgrade tc04005a_member_revoked_at` exited 0. `trust_article_versions` was gone. `tc17001_version_archive` held `(19, Keep, v1)`. `tc17001_ack_binding_archive` held version 19 and workspace 1. `alembic upgrade head` exited 0. The version row was `(19, Keep, v1, 1)`, `published_version_id` was 19, and the acknowledgment was version 19, workspace 1, `revoked_at` null. The synthetic article was then deleted.

`tests/release/test_trust_article_slug_workspace.py` also downgrades through this revision and upgrades to head. It passed in the neighbor run above.
