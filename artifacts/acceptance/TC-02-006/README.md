# TC-02-006 acceptance evidence: meaningful frontend unit, lint and formatting gates

- **Branch:** `tc/platform/TC-02-006`, stacked on `tc/platform/TC-02-003` (`73b9bb4`), which is based on master `f72def3`.
- **Tested commit:** `b53037927fdc49cdbdfd72436992e512e63cc9f3` (the last code commit). The evidence/docs commit on top changes no tested input. Check with `sha256sum -c artifacts/acceptance/TC-02-006/tested-inputs.sha256` at the PR head (15 files).
- **Baseline for the regression:** the TC-02-003 commit `73b9bb4`, checked out in a temporary worktree with this ticket's `test_web_quality.py` copied in.
- **Run date:** 2026-10-27 (UTC). Runner: `run-evidence.sh` (`BASE=<TC-02-003 sha>`). Logs are in `logs/` and exit codes in `summary.tsv`.
- **Environment:** Linux 6.12 x86_64 (Debian 13 box).
  - Node v24.22.1 and npm 11.19.1.
  - Python 3.13.5, pytest 9.1.1, ruff 0.5.6, pre-commit.
  - `NEXT_TELEMETRY_DISABLED=1`.
- **Pinned gate toolchain** (exact pins in `apps/web/package.json`, matching `package-lock.json`, printed in `logs/02-versions.log` and by the new CI step):

  | Tool | Version |
  |---|---|
  | TypeScript | 6.0.3 |
  | ESLint | 10.13.0 |
  | @eslint/js | 10.0.1 |
  | typescript-eslint | 8.72.1 |
  | eslint-plugin-react-hooks | 7.1.1 |
  | @next/eslint-plugin-next | 16.4.3 |
  | globals | 17.13.0 |
  | Prettier | 3.9.10 |
  | Vitest | 5.0.5 |
  | Next.js | 16.4.3 |

- **Data and network:** synthetic only.
  - No credentials, no `.env` and no production hosts.
  - The unit tests stub `fetch`, so the API proxy test opens no sockets.
  - Network was used only for the public npm registry (install and audit) and the pre-commit hook repos.
- **Install scripts:** every install used `npm ci --ignore-scripts`. The only locked package that declares an install script is still `fsevents`, a macOS-only optional dependency.
  - `eslint-config-next` was deliberately not adopted. It pulls in `unrs-resolver` (postinstall) and plugins capped at ESLint 9.

## Results

| # | Command (cwd) | Exit | Result |
|---|---|---|---|
| 00b | `python -m pytest tests/release/test_web_quality.py -q -rs` on the **baseline** (apps/api) | 1 | **8 failed, 8 passed, 10 skipped**. The failing regression covers no-op scripts, no ESLint config, no unit suite, vitest config, `.prettierignore`, pre-commit hook, CI gates and pinned tools. The skips are explained: the baseline has no ESLint installed. |
| 00c | baseline `npm run lint` | 1 | `Missing script: "lint"` |
| 00d | baseline `npm run test:unit` | 1 | `No test files found` |
| 00e | baseline `npm run format:check` | 1 | 83 files not formatted |
| 00f | baseline source linted with this ticket's config | 0 (report) | **25 errors and 8 warnings in 20 files** (`baseline-eslint.json`). By rule: no-unused-vars 16, no-location-assign 6, no-explicit-any 4, exhaustive-deps 2, static-components 2, no-html-link-for-pages 2, refs 1. |
| 00g | same, with `react-hooks/set-state-in-effect` enabled | 0 (report) | 56 errors and 8 warnings in 35 files, including 31 set-state-in-effect (`baseline-eslint-strict.json`). This is why that rule is off; see the ticket doc. |
| 01 | `npm ci --ignore-scripts --no-audit --no-fund` | 0 | clean install from the lock |
| 02 | tool versions | 0 | as tabled above |
| 03 | `npm run typecheck` (`next typegen && tsc --noEmit -p .`) | 0 | 0 type errors |
| 04 | `npm run lint` (`eslint . --max-warnings=0`) | 0 | 0 errors, 0 warnings |
| 05 | `npm run format:check` | 0 | all matched files formatted |
| 06 | `npm run test:unit` (`vitest run`) | 0 | **6 files, 46 tests passed, 0 failed, 0 skipped or todo** (`vitest-results.json`) |
| 07 | `npm run build` | 0 | built (Next 16.4.3) |
| 08 | `npm audit --omit=dev --audit-level=high` | 0 | 0 vulnerabilities |
| 09 | `npm audit --audit-level=low` (includes dev tools) | 0 | 0 vulnerabilities |
| 10 | `TC_REQUIRE_WEB_TOOLCHAIN=1 python -m pytest tests/release/test_web_quality.py tests/release/test_web_lock.py -q -rs` (apps/api) | 0 | **44 passed (26 quality + 18 lock), 0 failed, 0 skipped** |
| 11 | `ruff check` and `ruff format --check` on `tests/release/` | 0 | clean |
| 12 | `pre-commit run --files <every file changed since the TC-02-003 commit>` | 0 | all hooks pass, including prettier with `--ignore-path` |
| 13 | `npm run quality` (typecheck, lint, format:check, test:unit) | 0 | pass |

## How AC1 is shown (gates run real assertions, not missing or no-tests success)

- **Unit tests.** The suite has 46 tests: lib helpers, the auth `middleware`, and the `/api/[[...path]]` proxy (headers, CSRF origin fallback, body forwarding, upstream errors, 502 on unreachable upstream).
  - `passWithNoTests: false` is set.
  - The release test checks:
    - an empty selection fails ("No test files found");
    - a synthetic failing test makes vitest exit non-zero;
    - the JSON report has more than 30 tests and 0 failed, skipped or todo.
- **Lint.** `--max-warnings=0` runs over the full recommended rule sets.
  - The release test feeds synthetic violations on stdin and requires a non-zero exit with the expected rule IDs:
    - a hook called conditionally;
    - an unused variable;
    - an `any`;
    - `<img>` (Next).
  - Clean code must pass.
  - The release test also requires every `eslint-disable` to name a rule. There are no blanket disables.
- **Format.** A synthetic unformatted file fails `prettier --check` and a formatted one passes.
  - `.prettierignore` may list only generated paths. The release test enforces this.

## How AC2 is shown (type, build and format results with pinned versions)

Steps 02 to 07 record the type, build and format results next to the exact tool versions. `test_gate_tools_are_pinned_and_locked` and `test_installed_gate_tools_match_pins` require exact pins that match both the lock and the installed packages. CI prints the same versions in its "Frontend tool versions" step.

## Not done here

- **Reviewer sign-off** (DoD) is pending. A reviewer other than the implementer must accept this evidence.
- **Linked follow-ups assigned by the Coordinator.** These are out of scope here and are tracked separately. Full details are in `docs/release/tickets/TC-02-006.md`.
  - **TC-02-006a** (1 pt, TC Platform & Security, right after CI is green; needs a regression test): the `/api` proxy turns upstream 204/205/304 into 502.
  - **TC-02-006b** (5 pts, TC Web & UX): enable `react-hooks/set-state-in-effect` and refactor the 31 effects.
  - **TC-02-006c** (3 pts, TC Web & UX, after 006b): remove the 15 new lint suppressions.
  - **TC-02-006d** (2 pts, TC Platform & Security, after 006a): enforce the import, jsx-a11y and react plugin rules in the ESLint 10 flat config.
- **Coordinator decision:** the Coordinator accepted the custom ESLint 10 flat config in place of `eslint-config-next`.
- **The branch has not been pushed**, so no CI run of this branch exists yet. Master's `build` job is red from baseline for unrelated reasons, which another workstream is fixing.

## CI impact: `pre-commit run --all-files`, the CI step that is red on master

Logs 15 and 16 come from a local run, as in CI, on master `f72def3` and on this branch.

| Hook | master `f72def3` | this branch |
|---|---|---|
| ruff | Failed (479 errors, backend) | Failed (**same 479**, none in the new test file) |
| ruff-format | Failed (423 backend files would be reformatted) | Failed (**same 423**; both release test files already formatted) |
| prettier | **Failed** (apps/web unformatted) | **Passed** |
| trailing-whitespace / check-yaml | Passed | Passed |
| end-of-file-fixer | Failed (13 tracked generated files) | Failed (**identical 13-file list**) |

This branch causes no new CI failure. It fixes the prettier hook. The remaining failures were there before this change, are outside this ticket's scope, and are left to the CI-repair workstream.
