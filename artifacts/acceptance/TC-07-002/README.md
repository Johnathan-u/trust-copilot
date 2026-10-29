# TC-07-002 acceptance

No credential values are recorded here.

## Command

```
cd apps/api && python -m pytest tests/release/test_key_rotation.py -q
```

## Result

- Commit: `22ab4fc449a27885592e41342faca17714e57ec4`
- Environment: cloud agent VM, Python 3.12, `TC_REQUIRE_DB=1`, `SESSION_SECRET` set to a non-production test value, Postgres `pgvector/pgvector:pg16` (same image pin as CI)
- Exit status: 0
- Totals: 10 passed, 46 warnings

On master `6a26d60e44433720cf329cba08a8f096cb22e682` the same file fails at collection (`ModuleNotFoundError: No module named 'app.core.keys'`, pytest exit 2).

## Also run

- Fresh database: `alembic downgrade -1` returned to `tc21005_mapping_version`, then `alembic upgrade head` returned to the single head `tc07002_session_key_id`.
- Full backend suite, default order (release modules first): exit 0, 3155 passed, 1 skipped.
- Full backend suite, top-level tests first: exit 0, 3155 passed, 1 skipped.
- `python scripts/security/secret_inventory.py tree`: exit 0, 0 blocking.
