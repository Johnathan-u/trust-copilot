# TC-07-002 acceptance

No credential values are recorded here. Synthetic rows only.

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

Master's Alembic head is still `tc02001a_parent_ws_move`, so this branch was not re-parented.

## Also run

- Full backend suite, default order (release modules first): exit 0, 3283 passed, 1 skipped. Fresh database `tc07002_order_c_test`.
- Full backend suite, top-level tests first: exit 0, 3283 passed, 1 skipped. Fresh database `tc07002_order_d_test`.
- `ruff check` and `ruff format --check` from `apps/api`: exit 0.
- `python scripts/security/secret_inventory.py tree`: exit 0, 0 blocking.

The MFA and rotation tests delete the users, workspaces, members, MFA rows, recovery codes, sessions, credential rows and audit rows they created, by id, and assert those counts return to the starting values. Workspace ids are explicit. There is no `setval`.
