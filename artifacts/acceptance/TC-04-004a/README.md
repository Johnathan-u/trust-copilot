# TC-04-004a implementation evidence

Claim: [#85 comment 6514312794](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6514312794).
Base: `765589e9d3af2992e62f0d1e0cfc03296f444813`.
Branch: `codex/TC-04-004a-session-validation`. Exact implementation and separate master-integration commit/tree IDs are returned to the coordinator; no worker publication occurs.

Commands run from `apps/api` with `/tmp/tc-backend-venv/bin/python` and `/tmp/tc-backend-venv/bin/ruff`: Python 3.12.14, FastAPI 0.162.0, SQLAlchemy 2.0.55, pytest 9.1.1, Ruff 0.5.6, httpx 0.28.1. No dependency changes. All credentials and data in the new controls are synthetic.

| Check                                                                                                                 | Result                                                                                                 |
| --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `python -m pytest tests/release/test_session_validation.py -k 'not postgres' -q` on unchanged reviewed runtime        | 18 failed / 8 passed / 25 deselected; exit 1                                                           |
| Same command after runtime repair                                                                                     | 26 passed / 25 deselected; exit 0                                                                      |
| New session controls plus principal/MFA/signing/key local subset, command below                                       | 97 passed / 77 deselected; exit 0                                                                      |
| New session file and six affected release files with `--collect-only -q`                                              | 410 collected; includes 51 new session cases (25 SQLite, 25 PostgreSQL, one expiry-boundary control)   |
| Same seven release files under `TC_REQUIRE_DB=1`                                                                      | Exit 3 before tests: PostgreSQL connection refused on localhost:5432                                   |
| `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy python -m pytest -m unit -q` | 698 passed / 11 skipped / 3238 deselected; exit 0; existing unit-suite skips do not qualify PostgreSQL |
| Ruff check/format and Python compileall on ten changed Python files                                                   | Passed                                                                                                 |
| `git diff --check`                                                                                                    | Passed                                                                                                 |

The before/after run reproduces missing/null/coerced expiry, missing/blank/malformed SID, cross-user SID, string/boolean identity, invalid logout deletion/audit effects and the exact expiry boundary. It preserves required/optional/public behavior, checks no protected-row changes on denial, tests immediate revocation and exercises durable logout across three fresh child interpreters. Signing validation and request/DB authority are real; only the dependency that supplies the isolated database is overridden. No external provider, browser or production application lifespan is claimed.

Local related command:

```sh
python -m pytest tests/release/test_session_validation.py tests/release/test_principal_contract.py tests/release/test_mfa_reenrol_security.py tests/release/test_session_signing_key_migration.py tests/release/test_key_rotation.py -q -k 'not postgres and not fresh_database and not reencrypts and not resumes_from and not mfa_reenrol_when and not failures_are_audited and not helper_audits and not retired_session_rows'
```

The six permitted fixture files keep their original assertions and intentional invalid credentials. New valid actor rows are removed by exact user/session ownership, and table-count cleanup includes `user_sessions`. The uid-less negative fixture receives only valid session metadata while retaining its invalid human identity; its existing 403 assertions stay intact. The expired trust-request fixture retains expiry `-1` and now has a real SID, isolating its original failure reason. The legacy MFA cookie still lacks SID/expiry and remains denied.

Remaining qualification: independent review; actual PostgreSQL execution, including all adjusted domain fixtures and restart control; separate reviewable integration of landed master; exact final-head build/web-release-e2e on push and pull_request. No schema migration is added. Current-policy/session-age and remember-me behavior, typed/service principal work and owner/viewer/grant migration remain separate frozen requirements. Parent tickets are not marked complete.
