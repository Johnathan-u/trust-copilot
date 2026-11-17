# TC-04-005 session revocation evidence

Command, from `apps/api`:

```sh
python -m pytest tests/release/test_session_revocation.py -q --tb=short
```

The backlog command is the same file with `-q` only. `--tb=short` is how the saved logs were captured. Both runs collected 10 tests: five cases on SQLite and the same five on PostgreSQL.

## SHA

Production auth in both runs is `0fb552fc449c70b947406c855e10be170ed8f26a`. That commit already demotes, suspends, and removes by rewriting the membership row, then reads that row on the next request. The parent commit therefore passes this test once the file exists. It cannot show a failing-before log. The failing run below disables the re-read in the working tree and does not commit that edit. Master `41db7562` (#270) changes only the tracker and `docs/release/tickets/TC-14-001d.md`. It does not change the auth files cited in the ticket note.

`git diff apps/api/app/core/auth_deps.py` was empty before the passing run.

## Failing before

`resolve_current_membership` in `apps/api/app/core/auth_deps.py` returned the signed session immediately after the pending-account branch. The `WorkspaceMember` query under that return did not run. No other production file changed.

Exit status 1. 8 failed, 2 passed, 0 skipped. Log: [failing-before.txt](failing-before.txt).

Demotion returned the signed role `stale` instead of `reviewer`. Suspension, removal, and `/api/auth/me` for a suspended member returned 200 instead of 403.

The two passes are `test_admin_revoke_sessions_invalidates_the_cookie_and_leaves_api_keys` on SQLite and PostgreSQL. `POST /api/members/{id}/revoke-sessions` deletes `user_sessions` rows. It does not use the membership re-read, so disabling that re-read does not fail it.

## Passing after

The auth file was restored with `git checkout -- apps/api/app/core/auth_deps.py`. The same command then exited 0. 10 passed, 0 failed, 0 skipped. Log: [passing-after.txt](passing-after.txt).

## Environment

Local cloud VM, Linux x86_64. Python 3.12.3. pytest 9.1.1. SQLAlchemy 2.0.55. FastAPI 0.162.0. PostgreSQL 16.15, database `trustcopilot_test` on localhost, for the postgres parameter. The sqlite parameter uses a private in-memory database. No live provider was called. Notification dispatch on the member routes was replaced with a no-op so the cases do not depend on the notification schema. Authentication and the membership routes were not mocked.

## CI

`build` and `web-release-e2e` run IDs for qualifying head `d397e8e8259037a510efa678a3c320708c8e55db` are in [ci-runs.md](ci-runs.md). That head was squash-merged as `480b4ae19d14fc46b3638b341dad8d90f2fcec2f`.
