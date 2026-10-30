# TC-07-002 acceptance

No credential values are recorded here. Synthetic rows only.

## Local security repair, 2026-10-30

Branch: `codex/TC-07-002-repair-local`, based on existing PR #93 head
`8fe8e7d023700a748e2f08a7e8518352f523a7ea`. The repair preserves that history.
This section qualifies the repair working tree; the older PostgreSQL results below do not.

The repair covers stable HKDF reads when retaining `v0-legacy`, explicitly scoped compatibility
for the earlier SHA256 format, retirement of unprefixed session signatures, current persisted
administrator authorization for reset, and enrollment-only access after that reset. The
pending marker uses punctuation that cannot be a configured key id. It survives setup and
key re-encryption and is removed only after valid TOTP confirmation. Ordinary disabled
optional enrollment remains unchanged.

Environment: local Python 3.12.14, `/tmp/tc-backend-venv`, Ruff 0.5.6. No provider calls or
real credential rotation. SQLite tests call the actual routes, session dependencies, password
hashing, key functions and TOTP implementation against isolated synthetic rows. They do not
qualify PostgreSQL locking, migrations, concurrent requests or the browser UI. The only mocked
operation in the new tests is a commit failure, used to check rollback and cookie issuance.

Commands from repository root:

```sh
/tmp/tc-backend-venv/bin/python -m pytest -q apps/api/tests/release/test_keyring_compatibility.py apps/api/tests/release/test_mfa_reenrol_security.py --tb=short
```

Result: exit 0, **27 passed**, 70 existing `datetime.utcnow()` deprecation warnings.
Before the fixes, the initial regression set failed 15 tests and passed 4; those failures
included the four reported security defects. Subsequent cases cover ordinary disabled MFA,
stale normal cookies and optional auth, workspace switching, current role/suspension,
limited session metadata, invalid confirmation, rollback and marker preservation.

Commands from `apps/api` (the existing configuration and secret checks need no database):

```sh
/tmp/tc-backend-venv/bin/python -m pytest -q tests/release/test_secret_inventory.py tests/release/test_config_contract.py --tb=short --maxfail=3
/tmp/tc-backend-venv/bin/python -m pytest -q -m unit tests/release/test_key_rotation.py tests/release/test_secret_inventory.py tests/release/test_config_contract.py tests/test_auth_sessions_api.py tests/test_session_concurrency.py --tb=short --maxfail=3
```

The initial first command found three synthetic test literals matching the secret scanner;
they were replaced by generated values. Its other 901 tests passed. The second command passed
6 tests and deselected 922 (module classification makes this a narrow check, not broad coverage).
The final combined regression/configuration/secret and six existing pure-key checks are:

```sh
/tmp/tc-backend-venv/bin/python -m pytest -q \
  tests/release/test_keyring_compatibility.py \
  tests/release/test_mfa_reenrol_security.py \
  tests/release/test_secret_inventory.py \
  tests/release/test_config_contract.py \
  tests/release/test_key_rotation.py::test_purpose_keys_do_not_decrypt_each_other \
  tests/release/test_key_rotation.py::test_legacy_unprefixed_ciphertext_still_opens \
  tests/release/test_key_rotation.py::test_retired_session_key_is_rejected \
  tests/release/test_key_rotation.py::test_wrong_key_fails_closed_without_leaking \
  tests/release/test_key_rotation.py::test_production_rejects_reused_and_weak_keys \
  tests/release/test_key_rotation.py::test_prefixed_mfa_ciphertext_fits_the_column \
  --tb=short --maxfail=3
```

Final result: exit 0, **936 passed**, 70 existing `datetime.utcnow()` deprecation warnings.

Ruff commands from repository root, each with these exact file arguments:

```sh
/tmp/tc-backend-venv/bin/ruff check apps/api/app/core/keys.py apps/api/app/core/key_rotation.py apps/api/app/core/mfa.py apps/api/app/core/session.py apps/api/app/core/auth_deps.py apps/api/app/api/routes/auth.py apps/api/app/api/routes/members.py apps/api/tests/release/test_keyring_compatibility.py apps/api/tests/release/test_mfa_reenrol_security.py apps/api/tests/release/test_mfa_admin_reset.py
/tmp/tc-backend-venv/bin/ruff format --check apps/api/app/core/keys.py apps/api/app/core/key_rotation.py apps/api/app/core/mfa.py apps/api/app/core/session.py apps/api/app/core/auth_deps.py apps/api/app/api/routes/auth.py apps/api/app/api/routes/members.py apps/api/tests/release/test_keyring_compatibility.py apps/api/tests/release/test_mfa_reenrol_security.py apps/api/tests/release/test_mfa_admin_reset.py
git diff --check
```

Results: all three commands exited 0; Ruff reported all checks passed and all 10 files
already formatted.

### Unavailable qualification

From `apps/api`, `/tmp/tc-backend-venv/bin/python -m pytest -q --maxfail=5` stopped with
exit 1 after **5 setup errors and 1 skip**. Each setup error in
`tests/release/test_answer_sweep_direct_evidence.py` was PostgreSQL connection refused on
localhost:5432. The run was stopped at that limit rather than accumulating known infrastructure
errors. No full-backend pass is claimed for this repair. The existing PostgreSQL HTTP MFA test
has additional limited-login and successful-session-replacement assertions but was not run
locally. No migration file was changed; its parent must follow the actual landed master head
in a separate integration change. Independent review and exact-head CI remain coordinator work.
Owner decisions about KMS custody and sole-administrator recovery remain gated.
The existing acceptance of legacy cookies without a session id is unchanged after successful
enrollment clears the pending marker; those cookies are denied while the marker is present.
Pre-reset cookies with session ids remain invalid because their session rows were deleted.

## Historical evidence before the security repair

The following results are preserved for their original tested commit only.

## Command

```
cd apps/api && python -m pytest tests/release/test_key_rotation.py tests/release/test_mfa_admin_reset.py tests/release/test_session_signing_key_migration.py -q
```

## Result

- Commit under test: `fb162a8641b27fa1bde833a19a6388efd0b2dc4c`
- Environment: cloud agent VM, Python 3.12, `TC_REQUIRE_DB=1`, `SESSION_SECRET` set to a non-production test value, Postgres `pgvector/pgvector:pg16` (same image pin as CI), fresh database `tc07002_fix_test`
- Exit status: 0
- Totals: 15 passed (key rotation, MFA admin reset, and the signing-key round trip)

## Round trip

`tests/release/test_session_signing_key_migration.py` on a database of its own:

- `alembic upgrade head` to `tc07002_session_key_id`
- insert a synthetic session with `signing_key_id = v1`
- `alembic downgrade tc02001a_parent_ws_move` (the column is gone, the session row remains)
- `alembic upgrade head` (the column is back, null on the existing row)
- single head `tc07002_session_key_id`

At that earlier run, master's Alembic head was `tc02001a_parent_ws_move`, so the branch was not re-parented.

## Also run

- Full backend suite, default order (release modules first): exit 0, 3283 passed, 1 skipped. Fresh database `tc07002_order_c_test`.
- Full backend suite, top-level tests first: exit 0, 3283 passed, 1 skipped. Fresh database `tc07002_order_d_test`.
- `ruff check` and `ruff format --check` from `apps/api`: exit 0.
- `python scripts/security/secret_inventory.py tree`: exit 0, 0 blocking.

The MFA and rotation tests delete the users, workspaces, members, MFA rows, recovery codes, sessions, credential rows and audit rows they created, by id, and assert those counts return to the starting values. Workspace ids are explicit. There is no `setval`.
