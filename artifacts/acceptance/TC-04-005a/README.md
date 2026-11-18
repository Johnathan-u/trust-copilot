# TC-04-005a workspace-scoped revoke evidence

Local cloud VM, Linux x86_64. Python 3.12.3. pytest 9.1.1. SQLAlchemy 2.0.55. FastAPI 0.162.0. Interpreter `/tmp/tc-venv/bin/python`. No Postgres server is installed here, so the postgres parameter of both revocation modules skipped. CI runs those cases after `alembic upgrade head`. No live provider was called.

`alembic heads` on this branch is the single head `tc04005a_member_revoked_at`. Offline SQL from `tc17005a_share_token` adds nullable `workspace_members.sessions_revoked_at` (`TIMESTAMP WITHOUT TIME ZONE`).

This note does not accept TC-04-005 or TC-04-005a.

## Failing before

Working directory `apps/api`. The new tests were in the tree. The handler still deleted every `user_sessions` row for the user. The cutoff column and migration were not in the tree yet.

```sh
/tmp/tc-venv/bin/python -m pytest tests/release/test_tc04005a_revoke_scope.py -k "sqlite or migration" -q --tb=short
```

Exit status 1. 4 failed, 3 deselected, 6 warnings, 0.83s. Log: [failing-before.txt](failing-before.txt).

`test_workspace_revoke_leaves_the_other_workspace_session[sqlite]` got 401 `Session invalidated` for the session pointed at workspace B. Master had deleted that row with the workspace A session.

The stranger and self-service logout-all cases had already checked the HTTP results. They then read `sessions_revoked_at`, which the master model does not have (`AttributeError`). The migration test saw Alembic head `tc17005a_share_token`.

The switch-away assertions in the committed test sit after that 401. The red run stopped on the 401.

## Passing after

Same interpreter. The cutoff, the migration, and the switch-away check were in the tree.

```sh
/tmp/tc-venv/bin/python -m pytest tests/release/test_tc04005a_revoke_scope.py tests/release/test_session_revocation.py tests/release/test_shareable_space_token_migration.py::test_revision_is_the_single_head -rs --tb=line
```

Exit status 0. 10 passed, 8 skipped, 72 warnings, 3.81s. Log: [passing-after.txt](passing-after.txt).

The 10 passes are the three new sqlite cases, the migration head check, the TC-17-005a single-chain check, and the five sqlite cases in `test_session_revocation.py` (demotion, suspension, removal, suspend-does-not-revoke-keys, and the updated admin revoke). The 8 skips are the postgres parameter of those two modules. Each skip reason is `Postgres test database unavailable`.

The members confirm copy was checked with `npx --yes prettier@3.9.10 --check apps/web/app/dashboard/members/page.tsx` (exit 0). The dialog was not opened in a browser. This VM has no Postgres, and the screen needs a signed-in admin session.

## CI

Run IDs for `build` and `web-release-e2e` on push and pull_request are recorded in [ci-runs.md](ci-runs.md) after those runs finish.
