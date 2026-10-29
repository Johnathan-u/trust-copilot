# TC-03-002 acceptance evidence

Synthetic data only. No credential values are recorded here. No deploy was run.

| Item | Value |
|---|---|
| Baseline | `80607881320e1fa2c6416c55730eb98a56449f26` |
| Branch | `tc/platform/TC-03-002` |
| Alembic head | `tc02001a_parent_ws_move` (unchanged; no migration) |
| Compose test on baseline | 5 failed, 2 passed, exit 1 |
| Compose test on branch | 7 passed, exit 0 |
| Full API suite (fresh `*_test` database) | 3275 passed, 1 skipped, exit 0 |
| Secret scan | exit 0, `block` 0 |
| ruff / ruff format | `ruff check .` passed; `ruff format --check .` passed (672 files) |

The long-lived shared test database failed one pre-existing notification test (`test_control_verified_notifies`) because the first workspace control was already verified and a repeat verify does not notify. That failure is not from this ticket. The fresh database run is the suite result.

## Runtime
Postgres via `docker compose up` (project `tc03002`), user `999:999`, read-only root, `cap_drop ALL`, `no-new-privileges`. A synthetic row survived `compose restart`. Caddy, built from `infra/caddy/Dockerfile`, served on port 80 with `cap_drop ALL` plus `NET_BIND_SERVICE`. MinIO image pull was denied, so that restart check is pending.

Details: `commands.md`, `environment.txt`, `release-test-master.txt`, `release-test-branch.txt`, `full-suite.txt`, `runtime.txt`, `secret-scan.txt`.
