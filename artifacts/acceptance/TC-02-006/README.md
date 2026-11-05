# TC-02-006 acceptance evidence

Ticket: TC-02-006 (Jira SCRUM-47). Frontend unit, lint, and format gates.

## Verification on master (2026-11-05)

Re-ran the ticket gates on current master. No product change was required.

| Item | Value |
|---|---|
| Code under test | `130081c25e5414a7f9c5badb1eed37b167df8198` |
| Date | 2026-11-05 (UTC) |
| Host | Linux 6.12.94+ x86_64 |
| Node / npm | v24.22.1 / 11.19.1 (`.nvmrc` is `24.22.1`) |
| Python / pytest / ruff | 3.12.3 / 9.1.1 / 0.5.6, from `apps/api/requirements-dev.lock` |
| AC1 | pass |
| AC2 | pass |
| Release test | 26 passed, 0 failed, 0 skipped |
| Unit suite | 44 files, 426 passed, 0 failed, 0 skipped, 0 todo |

This evidence commit does not change the gate inputs. Hashes of those files at the tested SHA are in `verify-2026-11-05/tested-inputs.sha256`.

Command outputs, exit codes, and totals are in `verify-2026-11-05/` and `vitest-results-2026-11-05.json`. `verify-2026-11-05/summary.tsv` is `name`, exit code, directory, command.

| # | Command | cwd | Exit | Result |
|---|---|---|---|---|
| 11 | `npm ci --ignore-scripts --no-audit --no-fund` | `apps/web` | 0 | 399 packages from the lock |
| 01 | tool versions (`node`, `npm`, `tsc`, `eslint`, `prettier`, `vitest`, `next`) | `apps/web` | 0 | pins below |
| 02 | `npm run lint` | `apps/web` | 0 | `eslint . --max-warnings=0` |
| 03 | `npm run format:check` | `apps/web` | 0 | all matched files formatted |
| 04 | `npm run test:unit` | `apps/web` | 0 | 44 files, 426 tests passed |
| 05 | `npx vitest run --reporter=json --outputFile=artifacts/acceptance/TC-02-006/vitest-results-2026-11-05.json` | `apps/web` | 0 | `numTotalTests` 426, `numFailedTests` 0, `numPendingTests` 0, `numTodoTests` 0 |
| 06 | `npm run typecheck` | `apps/web` | 0 | `next typegen && tsc --noEmit -p .` |
| 07 | `npm run build` | `apps/web` | 0 | Next.js 16.4.3 production build |
| 08 | `npm run quality` | `apps/web` | 0 | typecheck, lint, format:check, test:unit |
| 09 | `TC_REQUIRE_WEB_TOOLCHAIN=1 python -m pytest tests/release/test_web_quality.py -q -rs -p no:cacheprovider` | `apps/api` | 0 | 26 passed, 0 skipped |
| 10 | `ruff check` and `ruff format --check` on `tests/release/test_web_quality.py` | `apps/api` | 0 | clean |

The local pytest interpreter was a venv installed with `pip install --require-hashes -r apps/api/requirements-dev.lock` and `pip install --no-deps -e apps/api`. CI installs that same lock on Python 3.11. Master push CI for this SHA is green: [run 42097709517](https://github.com/Johnathan-u/trust-copilot/actions/runs/42097709517) (`build` and `web-release-e2e`).

### Pinned toolchain (installed versions match `apps/web/package.json` and the lock)

| Tool | Version |
|---|---|
| TypeScript | 6.0.3 |
| ESLint | 10.13.0 |
| Prettier | 3.9.10 |
| Vitest | 5.0.5 |
| Next.js | 16.4.3 |
| Node | 24.22.1 |

`@eslint/js` 10.0.1, `typescript-eslint` 8.72.1, `eslint-plugin-react-hooks` 7.1.1, `@next/eslint-plugin-next` 16.4.3, and `globals` 17.13.0 are exact devDependency pins. The release test checks every gate tool pin against the lock and the installed package.

### AC1

`npm run lint` runs ESLint with `--max-warnings=0` over the flat config (ESLint recommended, typescript-eslint recommended, react-hooks recommended, Next.js core-web-vitals). `npm run test:unit` runs Vitest with `passWithNoTests: false`. The suite has 426 real assertions across 44 files, including `middleware.test.ts`, `api-proxy.test.ts`, and `api-error.test.ts`.

`apps/api/tests/release/test_web_quality.py` checks the scripts are present and are not no-ops, the unit suite covers every top-level runtime module under `apps/web/lib/` plus `middleware.ts` and `app/api/[[...path]]/route.ts`, and Vitest fails when no tests match and when an assertion fails. With the toolchain required, it also fails lint on a conditional hook, an unused variable, an `any`, and a Next `<img>`, and fails Prettier on an unformatted file. Those denial cases passed in the 26-test run. `TC_REQUIRE_WEB_TOOLCHAIN=1` leaves zero skips.

### AC2

`npm run typecheck`, `npm run format:check`, and `npm run build` exited 0 on this SHA. The `build` CI job prints `node`, `tsc`, `eslint`, `prettier`, and `vitest` versions, then runs lint, format check, unit tests, typecheck, and build in `apps/web` after `npm ci --ignore-scripts`. The pytest step sets `TC_REQUIRE_WEB_TOOLCHAIN=1`.

### Definition of done

| Item | Result |
|---|---|
| Both acceptance criteria demonstrated, evidence attached, no required skip | pass |
| `tests/release/test_web_quality.py` run, with command, SHA, environment, exit status, and totals recorded | pass |
| No contract change in this verification. Synthetic inputs only. No credentials in the new evidence | pass |
| `docs/release/tickets/TC-02-006.md` updated to this SHA | pass |
| A reviewer other than the implementer accepts the result | outstanding |

No migration or persisted state.

### Still outside this ticket

- TC-02-006a: `app/api/[[...path]]/route.ts` still builds `new NextResponse(responseBody, { status })` after `arrayBuffer()`, including null-body statuses 204, 205, and 304.
- TC-02-006d: import, jsx-a11y, and react plugin rules are still not part of the ESLint 10 flat config. The Coordinator accepted that config in place of `eslint-config-next`.
- Next.js prints a middleware-to-proxy deprecation during `npm run build`. The build exits 0. Moving `middleware.ts` is not part of this ticket.
- Independent reviewer sign-off is outstanding.

## Historical implementation record (2026-10-27)

`logs/`, `summary.tsv`, `vitest-results.json`, `baseline-eslint.json`, and `baseline-eslint-strict.json` are the original landing on `b53037927fdc49cdbdfd72436992e512e63cc9f3` (branch `tc/platform/TC-02-006`, merged as #10). That run recorded 6 unit files and 46 tests, and a baseline where lint was missing and the unit script reported no test files. Later product work grew the suite to the totals above. The release test count is still 26. Follow-ups #69 (TC-02-006b) and #71 (TC-02-006c) landed after that record: `react-hooks/set-state-in-effect` is `error`, and blanket `eslint-disable` comments fail lint.
