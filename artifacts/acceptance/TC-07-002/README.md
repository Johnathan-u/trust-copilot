# TC-07-002 acceptance

No credential values are recorded here. Synthetic rows only.

## Safe-collection fixture correction

Published head `cf5e3b22799ccfbada659678e13db7528caa28a2` failed the existing
safe-collection credential guard in push job `123834427104` (run `40985181291`).
The unreadable-MFA marker was a synthetic literal that matched that guard. The
same targeted check reproduced locally with one failure and one pass. The test
now generates its marker suffix and compares the stored marker to that original
value; no production code, scanner pattern or behavioral assertion changed.

From `apps/api`, `/tmp/tc-backend-venv/bin/python -m pytest
tests/release/test_safe_collection.py tests/release/test_keyring_compatibility.py
tests/release/test_mfa_reenrol_security.py -q` passed all 56 cases, with 70 existing
datetime deprecation warnings. Scoped Ruff lint/format and `git diff --check`
passed. This does not qualify PostgreSQL execution or final-head CI.

## Lossless migration repair, 2026-10-30

This repair is based on `8098052043b7ec2a9e2b8d32c0a6fe2270eb703a`, with the already
serialized parent `tc19010_inbox_receipts` unchanged. It addresses the independent review's
lossless-downgrade blocker under issue #85's ruling; it changes only the migration, its tests,
this evidence, and the ticket description.

Downgrade takes a PostgreSQL table lock, snapshots non-null signing-key metadata to a
migration-owned archive, and drops the column in the same transaction. Re-upgrade restores
only rows whose original primary key, user id, session id and creation time still match
(null-safe), then removes only successfully restored entries. Deleted sessions are never
inserted; replacement/reassigned sessions and new downgraded sessions keep a null key.
Unmatched entries remain archived across repeated cycles. A deliberately recreated row with
all four identity fields identical is indistinguishable from the original; this repair does
not introduce session lifecycle tracking or migration triggers.

Local Python 3.12.14 and Ruff 0.5.6, using `/tmp/tc-backend-venv`. The new SQLite tests import
and run the actual migration functions through Alembic Operations with transactional DDL.
They cover non-default and null keys, null and non-null creation time, deletion, primary-key
reuse with changed token/owner/time, reassignment, new rows, repeated cycles with changed keys,
unmatched archive retention, and rollback/retry after an injected restore failure. The test
failure injection uses a SQLite trigger; the production migration installs no triggers.

Commands from `apps/api`:

```sh
/tmp/tc-backend-venv/bin/python -m pytest tests/release/test_session_signing_key_migration.py -m unit -q
/tmp/tc-backend-venv/bin/python -m pytest tests/release/test_keyring_compatibility.py tests/release/test_mfa_reenrol_security.py -q
/tmp/tc-backend-venv/bin/python -m pytest tests/release/test_secret_inventory.py -q
TRUST_COPILOT_TESTING=1 /tmp/tc-backend-venv/bin/python -m alembic heads
TRUST_COPILOT_TESTING=1 /tmp/tc-backend-venv/bin/python -m alembic upgrade tc19010_inbox_receipts:tc07002_session_key_id --sql
TRUST_COPILOT_TESTING=1 /tmp/tc-backend-venv/bin/python -m alembic downgrade tc07002_session_key_id:tc19010_inbox_receipts --sql
```

The migration regressions first reproduced the loss with **9 failures** on the original
migration, then passed **9 tests, 1 deselected** with the repair. The separate keyring/MFA
checks passed **27 tests** with 70 existing `datetime.utcnow()` deprecation warnings;
secret-inventory checks passed **276 tests**. All commands exited 0 after repair.
Alembic reports one head, `tc07002_session_key_id`; both
PostgreSQL offline SQL directions render successfully, including the downgrade table lock.

Ruff check/format check on the migration and its test, plus `git diff --check`, passed.
The isolated PostgreSQL test now requires `v1` to survive the first round trip and `v2` the
second, checks null/replacement/new rows and unmatched archive retention, and accepts a
later descendant as the single head. PostgreSQL is unavailable locally, so that test and
actual PostgreSQL locking/DDL remain for CI; offline SQL and SQLite do not qualify them.
The known database-blocked full suite was not repeated. Independent review and exact-head
CI remain coordinator work; historical results below are not qualification for this repair.

## Landing integration, 2026-10-30

Pure master merge `0418fadd08d9546dc9e78980d837114ad6542ec5` incorporates
`5c4ffa0d550b0890ee4d8328d207eb96888535e2` without conflicts. A separate parent
change points this revision and its round-trip test to the actual landed
`tc19010_inbox_receipts`. `alembic heads` reports only `tc07002_session_key_id`;
the 27 focused keyring/MFA recovery regressions pass after integration.

Independent review found an additional release blocker: the original downgrade
discards non-null signing-key metadata and its old round-trip assertion expects
that loss. The lossless-downgrade ruling in issue #85 applies here. Repair and
non-default round-trip evidence are required before this branch qualifies.
No PostgreSQL migration execution or final CI pass is claimed locally.

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
