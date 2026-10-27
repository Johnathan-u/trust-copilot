# TC-21-002: Legacy and canonical control contract reconciliation

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework control text.

| AC | Result |
|---|---|
| AC1 Both routes agree on canonical ID, version, owner, lifecycle, and evidence | Met by `apps/api/tests/release/test_domain_controls.py`. Legacy and compliance payloads share one canonical object. A drifted stored lifecycle is reported, not rewritten, by GET. |
| AC2 Positive, negative, and partial-failure cases on PostgreSQL | Met by the same file. Admin is required to write. Reviewer and editor are refused. A workspace mismatch is 404. A foreign document and a foreign owner are rejected. A failed evidence mirror and a failed contract event stay retryable and do not insert a second row. |
| AC3 Public schema, UI consumer, and persisted outcome agree across retry | Met by the same file. The nested `canonical` object is `control-contract/v1`. Node 24 loads `apps/web/lib/controlContract.ts` and accepts the same block from either route. Retry returns the saved row. |

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_controls.py -q
```

## SHA

Tests ran on `d3145d20b53cc99481f3b6af03d8c5f15e2b25a7` (merge of `1c8456be724f66f7979a9e775ea7bc20c54a296e` with `origin/master` `58b8c879612ad21759805ab614fb2c4f59f39ada`). This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic 1.20.1
- Node 24.22.1 for the UI reader imported by the agreement test
- `alembic heads`: `tc21002_control_contract (head)`, parent `tc19008_notification_delivery`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_controls.py -q` | 0 | 6 passed, 0 skipped, 63 warnings, 5.04s |

No test in that file was skipped.

## CI repair

The first push of `e4e983619387be84c8fa0e0527660de03f42d71a` failed because the agreement test launched Node from `~/.nvm/versions/node/v24.22.1/bin/node`. GitHub Actions installs Node 24 from `apps/web/.nvmrc` onto `PATH` and does not create that path. The same `FileNotFoundError` failed push run 40522261910 and pull_request run 40522329512.

The test now uses `node` on `PATH` and requires a `v24` version. Re-run from `apps/api` with Node 24.22.1 first on `PATH`:

```text
python -m pytest tests/release/test_domain_controls.py -q
```

Exit 0. 6 passed, 0 skipped, 63 warnings, 4.40s.

Master then added `tc10003b_idempotency_owner_token` (parent `tc24001_stripe_webhook_events`). `tc21002_control_contract` was re-parented onto that revision. `alembic heads` showed one head, `tc21002_control_contract (head)`. The same pytest command passed again: exit 0, 6 passed, 0 skipped, 63 warnings, 4.29s.
