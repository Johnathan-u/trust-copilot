# TC-07-002a acceptance evidence

No credential values are recorded here. Synthetic checks only.

Worker: Grok (worker). This record does not accept the ticket and does not authorize a merge.
Independent review of `82d15097db8e64b6b464cfa1b4a939aae0d376a3` requested changes. This
follow-up addresses those items. It is not Coordinator acceptance.

Spec: `docs/release/tickets/TC-07-002a.md`.

## Correction

The first evidence row for the operator runbook was marked Pass. That mark was wrong.
Review of `82d1509` found the copy was taken while production could still write, the first
migration off derived keys was missing, sole-admin recovery did not require a second
approval, and the pending-enrolment marker was left for the operator to rebuild. Those
points are fixed in the follow-up. The runbook is re-checked, not accepted.

## What this follow-up changed

| Review item | What changed |
|---|---|
| Stop writers before the database copy | `docs/ops/key-rotation.md` now opens a maintenance window and stops the API and worker before the copy. |
| First migration off `v0-legacy` | The runbook sets each ring on the non-production copy to `new-kid:<generated>,v0-legacy:<session-secret>`, rotates, then gives production the new key only. `README.md` and `docs/release/config-contract.md` no longer tell production to keep the root as `v0-legacy`. |
| Sole-admin recovery | Recovery codes first, an out-of-band identity check, and a second person or the owner. The audit row records operator, approver, verification method, and change reference. The runbook warns that `user_mfa` is per user and affects every workspace. |
| Pending marker literal | The runbook gives `'reenrol-pending!.pending'` and a check query that must show `marker_ok` before `COMMIT`. |
| Leading space bypass | `production_key_problems` strips before comparing and refuses whitespace in a key. |
| Long placeholder | Key entries are also checked with `is_known_default_or_placeholder`. |
| Extra refusal tests | Weak retired entry, retired secret shared across rings, duplicate inside one ring, malformed ring text `is not a kid:secret list`, and the leading-space case. |
| Compose comment | `${VAR:?}` is documented as shell, Compose `.env`, or `--env-file`, not `env_file:`. |
| Copy host and backups | The rotation host is production-sensitive and is destroyed afterwards. Keyrings are not stored with database backups or snapshots. `CURRENT_TIMESTAMP` is documented as following the session time zone, with the session set to UTC. |

## Commands

From `apps/api`, Python 3.12.3, ruff 0.5.6. No database. `PYTHONPATH` included the locked dev dependencies.

```sh
python -m pytest tests/release/test_config_contract.py tests/release/test_secret_inventory.py tests/release/test_key_rotation.py::test_production_rejects_reused_and_weak_keys tests/release/test_keyring_compatibility.py -q --tb=line -p no:cacheprovider
ruff check app/core/keys.py app/core/config_contract.py tests/release/test_config_contract.py tests/release/test_secret_inventory.py
ruff format --check app/core/keys.py app/core/config_contract.py tests/release/test_config_contract.py tests/release/test_secret_inventory.py
```

Exit 0. Pytest: **964 passed** in 15.16s (`pytest-q.txt`). Ruff check and format check passed.
Output is counts and progress dots only.

## Limitation

Local Postgres was not accepting connections, so the database-backed cases in
`tests/release/test_key_rotation.py` were not re-executed. The non-database case
`test_production_rejects_reused_and_weak_keys` was included and passed.
`tests/release/test_session_persistence.py` was not modified and was not run.
