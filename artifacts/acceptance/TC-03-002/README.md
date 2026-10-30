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

## Runtime CI harness, 2026-10-30

Source parent: `92d61e6341f7772394c1ca896a0bc5c57b0baf05`. This change adds the
dedicated `Compose acceptance` workflow and `scripts/release/compose_acceptance.py`.
It does **not** supply a successful Docker run. The coordinator environment has no
Docker, so the actual hardened startup and persistence gates remain pending.

Local checks for this change:

| Command | Result |
|---|---|
| `cd apps/api && /tmp/tc-backend-venv/bin/python -m pytest tests/release/test_compose_stack.py -q` | 15 passed; exit 0 |
| `/tmp/tc-backend-venv/bin/ruff check scripts/release/compose_acceptance.py apps/api/tests/release/test_compose_stack.py` | passed; exit 0 |
| `/tmp/tc-backend-venv/bin/ruff format --check scripts/release/compose_acceptance.py apps/api/tests/release/test_compose_stack.py` | passed; exit 0 |
| `/tmp/tc-backend-venv/bin/python scripts/security/secret_inventory.py tree --root .` | 0 block findings; exit 0 |

Seven existing checks inspect committed declarations. Eight new cases check
harness isolation, preservation of image/security/command settings, refusal of
shared/external resources and self-hosted runners, credential redaction,
ownership checks before cleanup, and honest nonzero failure propagation. These
cases are not substitutes for Docker acceptance.

The CI artifact `compose-acceptance-<run>-<attempt>` records the exact tested SHA,
runtime image IDs, security settings, individual stage results and cleanup. It
must prove fresh and populated dev dependency-volume startup, six-service
production readiness, a PostgreSQL row and MinIO object surviving restart and
container recreation, and the same Caddy CA/autosave state with verified HTTPS.
Only sanitized reports and bounded failure logs are uploaded; generated env files,
raw inspect/config output, private keys and credentials are excluded.

The sole TLS fixture adjustment is localhost with Caddy's internal CA, retaining
the production proxy routes. Public ACME issuance remains outside this evidence.
The test preserves committed images and fails if the registry denies a pull. It
does not log in, substitute images, create accounts, call models, repair old
volumes, or change checkout ownership. A dev `.next` write-permission failure
would be retained as a source/runtime blocker, not worked around by the harness.
