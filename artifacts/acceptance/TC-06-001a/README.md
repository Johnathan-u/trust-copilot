# TC-06-001a local repair evidence

Claim: #85 comment `6513354940`. Base:
`c2ac170f2a1572811342af67abfa4e703b14a628`. Branch:
`codex/TC-06-001a-current-membership`. Worker changes are local only; the coordinator
owns publication, independent review and exact-head CI.

Commands below run from `apps/api` using `/tmp/tc-backend-venv/bin/python` and the
existing environment: Python 3.12.14, FastAPI 0.162.0, SQLAlchemy 2.0.55, pytest
9.1.1, Ruff 0.5.6 and httpx 0.28.1. No dependency changes. SQLite HTTP tests use real route/dependency logic and separate
request sessions, with foreign keys enabled. They do not qualify PostgreSQL,
production middleware/startup, external providers or browser behavior.

## Results

| Command/control | Result |
| --- | --- |
| `python -m pytest tests/release/test_principal_contract.py -k sqlite -q` against exact base versions of the two runtime files | 14 failed, 8 passed, 22 deselected; exit 1. Both files restored immediately after the control |
| Same command against repaired runtime files | 22 passed, 22 deselected; exit 0 |
| `python -m pytest tests/release/test_principal_contract.py --collect-only -q` | 44 collected; exit 0 |
| `TC_REQUIRE_DB=1 python -m pytest tests/release/test_principal_contract.py -k postgres -q` | Exit 3 before test execution; localhost PostgreSQL connection refused |
| `ruff check app/core/auth_deps.py app/api/routes/auth.py tests/release/test_principal_contract.py` | Exit 0 |
| `ruff format --check app/core/auth_deps.py app/api/routes/auth.py tests/release/test_principal_contract.py` | Exit 0; all three formatted |
| `git diff --check` | Exit 0 |

The baseline failed on current role resolution, required missing-membership
denial, optional removed/suspended-member denial, `/me` authority, suspended
workspace switching and pending-onboarding business access. The repaired cases
also preserve anonymous published content, valid bearer-key behavior, real
first-workspace creation, restricted MFA enrollment and exact fixture cleanup.

## Existing regression controls

The initial related run included the MFA reenrollment, MFA admin reset, signing-key
migration, key rotation, workspace creation policy and session API files. It had
32 passes, 28 skips, 1 failure and 8 setup errors, exit 1. The failure and setup
errors were unavailable PostgreSQL connections; the skips were PostgreSQL-backed
fixtures. No product/fixture assertion failure from missing membership was found
in runnable controls. No existing test file was edited.

The runnable controls were then selected explicitly:

```sh
python -m pytest tests/release/test_mfa_reenrol_security.py tests/release/test_session_signing_key_migration.py tests/release/test_key_rotation.py -q -k 'not fresh_database and not reencrypts and not resumes_from and not mfa_reenrol_when and not failures_are_audited and not helper_audits and not retired_session_rows'
```

Result: 26 passed, 7 deselected, exit 0. This includes real local MFA reset/login,
restricted enrollment, current-role confirmation, session replacement and failed
confirmation controls. Deselected PostgreSQL controls remain required in CI.

```sh
python -m pytest tests/release/test_workspace_creation_policy.py -q -k 'default_policy or unknown_policy or settings_are_registered or contract_validates or in_memory_limiter'
```

Result: 6 passed, 24 deselected, exit 0. Full existing onboarding/session HTTP tests
still require PostgreSQL; new SQLite HTTP coverage is additional evidence only.

## Tested code identity and remaining gates

| File | Git blob |
| --- | --- |
| `app/core/auth_deps.py` | `88f944cdc613a55ae615990031ab8f9ea84b8203` |
| `app/api/routes/auth.py` | `b8abea0f54f5c0d4fe5ec54346ffede0c8e8b17d` |
| `tests/release/test_principal_contract.py` | `afc0e41a848d8342d7da97bee3e1803dd31c0082` |

`verification.txt` preserves selected actual output, with synthetic bearer values
redacted if present. Existing datetime deprecation warnings remain. PostgreSQL
execution, independent review and exact final-head build/web-release-e2e checks
on push and pull_request remain pending. The frozen parent tickets are open;
this evidence covers only the claimed current-membership child.
