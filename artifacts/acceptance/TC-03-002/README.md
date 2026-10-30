# TC-03-002 acceptance evidence

Synthetic data only. No credential values are recorded here. No deploy was run.

## Dev write-path repair, 2026-10-30

Independent source review found that the dependency stage installs as root while
the dev stage runs `npm ci` as node against a named dependency volume. The dev
stage now owns that image directory as node before a fresh volume is populated,
and directs npm's cache to the existing writable `/tmp`. Production-stage output,
non-root runtime users, read-only root filesystems and capability limits are unchanged.

Docker is unavailable in the coordinator runtime. This configuration repair does
not establish successful container startup, a full Compose smoke test, or MinIO
persistence. Those runtime acceptance gates remain pending. The seven existing
Compose checks cover declared hardening and volumes, not live filesystem access.

An existing root-owned `web_node_modules` volume does not acquire new ownership
when the image is rebuilt. Inspect that dependency-only volume before reusing it;
a local operator must arrange its node ownership separately. Do not recursively
chown the host source checkout or any database/object-storage volume. No such
operation was performed by this repair.

| Item | Value |
|---|---|
| Baseline | `80607881320e1fa2c6416c55730eb98a56449f26` |
| Branch | `tc/platform/TC-03-002` |
| Alembic head | `tc02001a_parent_ws_move` (unchanged; no migration) |
| Compose test on baseline | 5 failed, 2 passed, exit 1 |
| Compose test on branch | 7 passed, exit 0 |
| Full API suite after merging master `b70ba0f` | 3281 passed, 1 skipped, exit 0 |
| Secret scan | exit 0, `block` 0 |
| ruff / ruff format | `ruff check .` passed; `ruff format --check .` passed (672 files) |

Master moved from `8060788` to `b70ba0f` (TC-10-001b) before push. That commit is merged with `--no-ff` as `16930e9405fa0f704bc695cbbe52b049c584adac`. Alembic stays a single head, `tc02001a_parent_ws_move`.

The long-lived shared test database failed one pre-existing notification test (`test_control_verified_notifies`) because the first workspace control was already verified and a repeat verify does not notify. That failure is not from this ticket. The fresh database run above is the suite result, repeated after the merge.

## Runtime
Postgres via `docker compose up` (project `tc03002`), user `999:999`, read-only root, `cap_drop ALL`, `no-new-privileges`. A synthetic row survived `compose restart`. Caddy, built from `infra/caddy/Dockerfile`, served on port 80 with `cap_drop ALL` plus `NET_BIND_SERVICE`. MinIO image pull was denied, so that restart check is pending.

Details: `commands.md`, `environment.txt`, `release-test-master.txt`, `release-test-branch.txt`, `full-suite.txt`, `runtime.txt`, `secret-scan.txt`.
