# TC-05-001a evidence

Base: `c902d2ccf8d084398694928fe899be89acfefb08`.
Branch: `fix/TC-05-001a-provider-mfa`.
Claim: [#85 comment 6978152079](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6978152079).

No credential values are recorded here. Synthetic rows only. Provider token
exchange is mocked. The callback, MFA token and session cookie are the real
handlers. No live Google, GitHub, Microsoft, OIDC or ID.me call was made.

## Before the repair

Command, from `apps/api`, against the tests on this branch and the login code
at the base commit. Python 3.12.3, pytest 9.1.1. SQLite only. PostgreSQL was
not running on this machine, so the matching PostgreSQL cases skipped.

```sh
python -m pytest tests/release/test_mfa_enroll.py --tb=line -rs
```

Exit 1. **23 failed, 9 passed, 32 skipped**, 128 warnings. The warnings are the
existing `datetime.utcnow` deprecation. The 9 passes are password login with an
enabled factor, and sign-in with no enabled factor and no `mfa_required` (all
six paths, plus a disabled factor with no requirement on password and GitHub).
The failures are the five provider callbacks issuing an admin session before
any challenge, and every path issuing the member role when `mfa_required` is
set and no factor is enabled. Output:
[failing-before.txt](failing-before.txt).

## After the repair

Same command. Exit 0. **32 passed, 32 skipped**, 154 warnings, 4.45s. The skips
are the same PostgreSQL cases. Output: [passing-after.txt](passing-after.txt).

With the same interpreter, these SQLite controls also passed (PostgreSQL cases
in those files skipped for the same reason):

```sh
python -m pytest tests/release/test_mfa_enroll.py \
  tests/release/test_mfa_reenrol_security.py \
  tests/release/test_remember_policy.py \
  tests/release/test_session_persistence.py \
  tests/release/test_principal_contract.py -q --tb=line
```

180 passed, 169 skipped.

From `apps/web`, Node 24.22.1: `npm run lint`, `npm run format:check` and
`npm run test:unit` passed (59 files, 548 tests).

`ruff check` on the edited Python files passed, and `ruff format` was applied.
PostgreSQL execution of the same cases is the CI `build` job. This file does
not record run ids.
