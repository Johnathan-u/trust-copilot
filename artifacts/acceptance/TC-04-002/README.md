# TC-04-002 recoverable reset sends, single-use and race-safe redemption

Parent before the auth change: `d69109e720df3a697ff4af9eb1b222ae1553a628`.

No migration. A failed reset or verification send rolls the new row back on a background session and leaves a previously delivered code or link. The HTTP handler returns before the provider is called, so a known address is not slower than an unknown one. Reset, verification-link, and invite redemption each lock the row so two in-flight submits cannot both succeed.

## Failing before

`apps/api/app/api/routes/auth.py` was the parent file. `forgot_password` deleted unused reset rows, committed a new one, returned the generic 200 (and the dev URL when the flag was set), then sent mail on a background thread. A false or raised send left the caller with no working link. `reset_password` read the unused row without a lock, so two overlapping submits of that same token both returned 200.

Command, from `apps/api`:

```sh
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_identity_tokens.py -q --tb=line
```

Exit status 1. 4 failed, 3 passed, 0 skipped. Log: [failing-before.txt](failing-before.txt).

The rejected send, the raised send, and a first send with no earlier link failed. The concurrent redeem failed with codes `[200, 200]` and both requests reached password hashing (`arrived=2`). The digests in that log are SHA-256 of the tokens, not the raw links. The addresses are synthetic `@example.test` users, removed at the end of each test.

The three passes were already true on the parent: a later accepted send replaces the older link, a used token is rejected the second time, and a known address and an unknown address share one JSON body when the dev URL flag is off.

## Passing after

The same named command then exited 0. 7 passed, 0 failed, 0 skipped.

The existing reset neighbor, the registration reset test, the security-remediation invalidation class, the auth-flow file, and the login/email regression file:

```sh
python -m pytest tests/release/test_password_reset.py tests/release/test_registration.py::test_verification_and_password_reset_end_prior_sessions tests/test_security_remediation.py::TestPasswordResetTokenInvalidation tests/test_auth_flows.py tests/test_login_email_regression.py -q --tb=line
```

Exit status 0. 38 passed, 0 failed, 0 skipped.

Both logs: [passing-after.txt](passing-after.txt).

## Environment

Local cloud VM, Linux x86_64. Python 3.12.3. pytest 9.1.1. SQLAlchemy 2.0.55. FastAPI 0.162.0. Alembic 1.20.1. cryptography 50.0.2. ruff 0.5.6. PostgreSQL 16.15, database `trustcopilot_test` at 127.0.0.1:5432, user `postgres`.

`ruff check app/api/routes/auth.py tests/release/test_identity_tokens.py` exited 0. `ruff format` was run on both files before the passing run.

No live email provider was called. The tests install an in-process provider that returns true, returns false, or raises. The forgot-password page was not changed: a failed send is the same HTTP 200 as a successful one, which is the anti-enumeration choice recorded in `docs/release/tickets/TC-04-002.md`.

## CI

`build` and `web-release-e2e` run IDs for the implementation head are in [ci-runs.md](ci-runs.md).
