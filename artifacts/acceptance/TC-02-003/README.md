# TC-02-003 acceptance evidence — Upgrade and lock supported frontend dependencies

- **Base SHA:** evidence was produced on `c20f949161ac12a619b396d30904448ffd74d532`; the branch was then
  rebased onto master `f72def3` (docs-only commits under `docs/acceptance/` and `artifacts/acceptance/TC-01-*`,
  no overlap with any tested input — `sha256sum -c tested-inputs.sha256` still passes). Branch `tc/platform/TC-02-003`.
- **Tested tree:** the working tree whose inputs are hashed in `tested-inputs.sha256`
  (verify with `sha256sum -c artifacts/acceptance/TC-02-003/tested-inputs.sha256` at the PR head).
- **Run date:** 2026-10-27 (UTC). Runner script: `run-evidence.sh` (logs in `logs/`, exit codes in `summary.tsv`).
- **Environment:** Linux 6.12 x86_64 (Debian 13 box); Node v24.22.1 / npm 11.19.1 (official tarball,
  SHA256 verified); Python 3.13.5, pytest 9.1.1, ruff 0.5.6 (matches `.pre-commit-config.yaml`);
  Docker 26.1.5; Trivy 0.76.1 (release checksum verified). `NEXT_TELEMETRY_DISABLED=1`.
- **Data / network:** synthetic only. No credentials, no `.env`, no production hosts. The container
  smoke test ran with `--network none`. Network use was limited to the public npm registry
  (install/audit), Docker Hub (base image pull) and the Trivy vulnerability DB download.
- **Install scripts:** every install used `--ignore-scripts`. The only locked package declaring an
  install script is `fsevents` (macOS-only optional dependency, not installed on Linux).

## Results

| # | Command (cwd) | Exit | Result |
|---|---|---|---|
| 00 | `python -m pytest tests/release/test_web_lock.py -q` on **baseline c20f949** (apps/api) | 1 | **11 failed, 7 passed** — regression proves the checks detect the baseline gaps |
| 00 | baseline `npm run test:unit` (apps/web, Next 14) | 1 | "No test files found" (context for TC-02-006) |
| 00 | baseline `npm audit` (apps/web) | 1 | 14 vulns: **3 critical, 6 high**, 5 moderate (`baseline-npm-audit-summary.json`) |
| 01 | `npm ci --ignore-scripts --no-audit --no-fund` (apps/web) | 0 | clean install from lock |
| 02 | `npm run typecheck` = `next typegen && tsc --noEmit -p .` | 0 | 0 type errors |
| 03 | `npm run build` (Next 16.4.3, Turbopack) | 0 | 37 routes built, standalone output |
| 04 | `npm audit --omit=dev --audit-level=high` | 0 | 0 vulnerabilities (runtime) |
| 05 | `npm audit --audit-level=low` | 0 | 0 vulnerabilities (runtime + dev) |
| 06 | `python -m pytest tests/release/test_web_lock.py -q -p no:cacheprovider` (apps/api) | 0 | **18 passed, 0 failed, 0 skipped** |
| 07 | `ruff check` + `ruff format --check` on the new test | 0 | clean |
| 08 | `docker build -f apps/web/Dockerfile --target production .` | 0 | built |
| 09 | `docker build -f apps/web/Dockerfile --target dev .` | 0 | built (compose dev target still works) |
| 10 | image contents check | 0 | runs as `node`; only next/react/react-dom/sharp/styled-jsx (+deps) in node_modules; typescript, vitest, playwright, prettier, tailwind, postcss, esbuild, vite, eslint, npm, npx, corepack, `next` CLI **absent**; /app = 47 MB |
| 11 | container smoke (`--network none`) | 0 | `GET /login` 200; `GET /dashboard` 307 → `/login?next=%2Fdashboard` (middleware still enforced) |
| 12 | `trivy image --scanners vuln --severity HIGH,CRITICAL` | 0 | Node.js packages: **0**. OS (Debian 13.7): 0 critical, 43 HIGH findings / 8 CVEs, all **no fix available** — triage below |

## AC2 triage: OS-package HIGH findings in `node:24.22.1-trixie-slim`

None has a fixed Debian package yet (status `affected`/`fix_deferred`), so they are unresolved
upstream. None is reachable from the running service: the container runs `node server.js` as the
unprivileged `node` user, never invokes a shell utility, mount helper, `nsenter`, `login`,
systemd-homed, ncurses programs or Perl, and processes no tar archives.

| CVE | Packages | Why not reachable |
|---|---|---|
| CVE-2026-76642, -78408, -78409, -78410 | util-linux family (mount, nsenter, login, libmount, libblkid, ...) | privileged mount/nsenter helpers; never executed, process is non-root |
| CVE-2026-54369 | libacl1 | ACL symlink traversal via libacl callers; no caller in the app |
| CVE-2026-16742 | libsystemd0, libudev1 | systemd-homed LPE; no systemd/homed in a container |
| CVE-2025-69720 | ncurses | terminal UI library; no TTY programs run |
| CVE-2026-9538 | perl-base (Archive::Tar) | Perl never invoked |

The bookworm-slim variant was also scanned (57 HIGH + 1 CRITICAL `zlib1g` CVE-2023-45853 will_not_fix),
which is why trixie-slim was chosen. Re-scan on every base-image bump; a distroless runtime is a
possible follow-up (needs compose healthcheck changes, out of scope here).
