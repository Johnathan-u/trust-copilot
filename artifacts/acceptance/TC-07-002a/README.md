# TC-07-002a acceptance evidence

No credential values are recorded here. Synthetic checks only.

Worker: Grok (worker). This record does not accept the ticket and does not authorize a merge.
Independent review is still required. OD-14 says no separate owner sign-off is needed for this
ticket; that decision is the Coordinator's to record, not the implementer's.

Spec: `docs/release/tickets/TC-07-002a.md`.

## What was checked

| Criterion | Result | Evidence |
|---|---|---|
| Production refuses to start unless `SESSION_KEYRING`, `OAUTH_STATE_KEYRING`, `MFA_KEYRING` and `CONNECTOR_KEYRING` are set, strong, distinct from each other, and distinct from `SESSION_SECRET`. Messages name the variable only. Development and test are unchanged. | Pass | `apps/api/app/core/keys.py` `production_key_problems`; `apps/api/app/core/config_contract.py`. `tests/release/test_config_contract.py`. |
| `docker-compose.prod.yml`, `.env.example` and generated `docs/release/config-contract.md` require all four. Release tests cover missing, weak, duplicate, and equal to `SESSION_SECRET`. | Pass | Compose `${VAR:?}` on api and worker. Contract table regenerated with `python -m app.core.config_contract markdown`. |
| Operator runbook covers copy-then-cut-over rotation, keyring backup, and sole-admin MFA recovery with an audit row. | Pass | `docs/ops/key-rotation.md`. `test_key_rotation_runbook_covers_backup_rotation_and_recovery`. |

## Commands

From `apps/api`, Python 3.12.3, ruff 0.5.6. No database. `PYTHONPATH` included the locked dev dependencies.

```sh
python -m pytest tests/release/test_config_contract.py tests/release/test_secret_inventory.py tests/release/test_key_rotation.py::test_production_rejects_reused_and_weak_keys tests/release/test_keyring_compatibility.py -q --tb=line -p no:cacheprovider
ruff check app/core/keys.py app/core/config_contract.py tests/release/test_config_contract.py tests/release/test_secret_inventory.py
ruff format --check app/core/keys.py app/core/config_contract.py tests/release/test_config_contract.py tests/release/test_secret_inventory.py
```

Exit 0. Pytest: **956 passed** in 15.04s (`pytest-q.txt`). Ruff check and format check passed.
Output is counts and progress dots only.

## Limitation

Local Postgres was not running, so the database-backed cases in `tests/release/test_key_rotation.py`
were not re-executed. Those cases do not call the new production keyring requirement. The existing
non-database case `test_production_rejects_reused_and_weak_keys` was included and passed.
`tests/release/test_session_persistence.py` was not modified and was not run.
