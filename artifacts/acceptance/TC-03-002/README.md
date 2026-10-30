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

## First Docker CI result and dev output repair — 2026-10-30

| Item | Observed evidence |
|---|---|
| Tested commit | `8afe9c8339ece620a9e1a6292d8e6b07d34a76c0` |
| Push run / job | [40986919877 / 123839978909](https://github.com/Johnathan-u/trust-copilot/actions/runs/40986919877/job/123839978909) |
| Uploaded artifact | `12946989052`, `compose-acceptance-40986919877-1` |
| Dev dependency install | `npm ci` added 399 packages in 8 seconds |
| Dev startup | Failed: `EACCES: permission denied, mkdir '/app/.next/dev'` |
| Checkout/runtime identity | Checkout UID 1001; committed web runtime UID 1000 |
| Production | `minio/minio:latest` pull access denied/not found; startup and persistence not executed |
| Cleanup | Dev and production project cleanup both passed |
| Overall acceptance | Failed; no startup/restart/persistence pass claimed |

The sanitized uploaded result is preserved as
[`runtime-ci-40986919877.json`](runtime-ci-40986919877.json). The `EACCES` path and
successful package-install excerpt above are from that artifact's `dev.log`.

The bounded repair adds a dev-only `web_next:/app/.next` named volume and prepares
`/app/.next` with node ownership in the dev image. It preserves the source bind,
`web_node_modules`, runtime user, read-only root, dropped capabilities and existing
acceptance assertions. No host source ownership change or existing data-volume
operation is included. The harness's dev-volume map retains `web_next` so the
test exercises the committed mount. Production Compose and the denied MinIO
image remain unchanged; public ACME is still outside this test.

Local validation for the follow-up: 15 Compose/harness tests passed, Ruff and
format checks passed, and `git diff --check` passed. These checks do not establish
that the container now starts; the new source head still requires independent
review and fresh Docker CI. The MinIO registry failure remains unresolved.

## Read-only dev declaration follow-up — 2026-10-30

Base: `7303c15c7c8e98b32cd7edc5b8257b398612e902`. Scope authorized in issue #85
comment `6513046846`. This follow-up addresses the next write path identified by
independent review; it does not claim the preceding `.next` volume repair passed
Docker acceptance.

Installed Next **16.4.3** appends `/dev` to the development output directory and
generates imports for `.next/dev/types/routes.d.ts` and
`.next/dev/types/root-params.d.ts`. Its config schema rejects
`experimental.isolatedDevBuild` as an unrecognized key. The production declaration
has `.next/types` imports, so dev would try to overwrite it in the source bind.

`infra/web/next-env.dev.d.ts` was generated by that installed Next implementation,
then mounted read-only at `/app/next-env.d.ts` in dev Compose. The exact comparison
test loads the current dev config and verifies the installed Next package equals
the pinned project version. It compares the generated bytes with the fixture,
sets only the temporary output file's timestamp to zero, and verifies a second
generator call leaves that timestamp unchanged. This proves the matching-content
no-write path, without changing checkout ownership or suppressing a generator
error. Another test checks the canonical read-only overlay survives `isolate`,
alongside both `web_node_modules` and `web_next`.

Local command, from `apps/api`:

```text
NODE_PATH=/workspace/scratch/ac0fa793e50b/tc-alerts-repair/apps/web/node_modules /tmp/tc-backend-venv/bin/python -m pytest tests/release/test_compose_stack.py -q
```

Result: **17 passed**, exit 0. `NODE_PATH` reused the already installed Next 16.4.3
from the sibling worktree; the test checks its version against this worktree's
pin. No dependency was added or upgraded. CI uses its normal `apps/web/node_modules`
installation. Missing Node/Next and fixture mismatch fail rather than skip.

Ruff, formatting and `git diff --check` pass. Production Compose, the tracked
production declaration and Next config are unchanged. These are generator and
source-contract checks, not live Docker acceptance. Independent review and fresh
Docker CI are still required; MinIO access and public ACME remain unqualified.
