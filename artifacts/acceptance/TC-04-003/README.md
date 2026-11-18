# TC-04-003 password reset and change-password revocation

Parent before the auth change: `787976e9d7aee40c3cf0a5d5a94d74155fba32c1`.

No migration. `password_reset_tokens.used_at` and `user_sessions` already exist. A successful reset deletes unused reset rows for that user. A successful password change deletes the other session rows.

## Failing before

`apps/api/app/api/routes/auth.py` was the parent file. `reset_password` set `used_at` on the one matched row and deleted sessions. It left the user's other unused reset rows. `change_password` deleted other sessions only when `invalidate_other_sessions` was true.

Command, from `apps/api`:

```sh
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_password_reset.py -q --tb=line
```

Exit status 1. 3 failed, 2 passed, 0 skipped. Log: [failing-before.txt](failing-before.txt).

The reset test's other unused token returned 200. With the flag false, and with the flag omitted, the second session's `GET /api/auth/me` returned 200. The flag-true case already returned 401 for that second session, and a wrong current password did not revoke either session. Those two passed.

## Passing after

The same named command then exited 0. 5 passed, 0 failed, 0 skipped.

The existing reset neighbor and the auth-flow file:

```sh
python -m pytest tests/release/test_registration.py::test_verification_and_password_reset_end_prior_sessions tests/test_security_remediation.py::TestPasswordResetTokenInvalidation tests/test_auth_flows.py -q --tb=line
```

Exit status 0. 13 passed, 0 failed, 0 skipped.

Both logs: [passing-after.txt](passing-after.txt).

## Environment

Local cloud VM, Linux x86_64. Python 3.12.3. pytest 9.1.1. SQLAlchemy 2.0.55. FastAPI 0.162.0. Alembic 1.20.1. cryptography 50.0.2. ruff 0.5.6. PostgreSQL 16.15, database `trustcopilot_test` at 127.0.0.1:5432, user `postgres`.

`ruff check app/api/routes/auth.py tests/release/test_password_reset.py` exited 0.

From `apps/web`, Node 24.22.1, Vitest 5.0.5: `npx vitest run tests/unit/logout-all.test.ts` exited 0. 19 passed. That file renders the account security page in happy-dom, opens Change Password, and submits a mocked request. ESLint on the page and that test exited 0. No logged-in browser session was required for the API assertions. The password-form check in that unit file is the UI check run locally.

## CI

`build` and `web-release-e2e` are green on push and pull_request for implementation head `7a9b0f8609a38ebd9128deeb2caa3504ef7e7706`. Run IDs are in [ci-runs.md](ci-runs.md). The first head failed `ruff-format` and is not qualifying.
