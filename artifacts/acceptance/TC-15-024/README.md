# TC-15-024 local acceptance evidence — 2026-10-30

Base: `35384fd1907ac9235922a74a575a1630aa0519ec`.
Branch: `codex/TC-15-024-outbound-ui`. Claims/rulings: #85 comments `6512668742`
and `6512889661`. The coordinator owns independent review, publication and merges.
All commands below run from `apps/web`, with Node v24.22.1 and the existing locked
dependencies. No dependency changes are included. Coordinator commit `26bca0e`
subsequently integrated the CI candidate/count/axe configuration.

## CI failure repair — claim 6513403408

The original published snapshot `570ad2050ec60ff3d200980741eced1489a2fd2b`
(local `b492341`, identical tree `2a385b666c7ecd84e0555d4d1b1a784184c94c34`)
failed five ui-22 cases on push run `40990778241`/job `123852377643` and PR run
`40990791296`/job `123852420096`. Seventeen ui-22 cases and all other release
cases passed; six fresh ticket axe reports contained zero violations. The push
job log was fetched directly during this investigation.

The repair addresses eager duplicate Strict Mode reads, unhandled owned
cancellation, and supplementary questionnaire success masking a primary-list
failure. Browser assertions retain exactly one destination document, one business
fetch, no analytics and Back behavior. Same-document Next history bookkeeping is
no longer counted as a second document navigation. Mutation assertions target the
actual row alert and its message rather than global live regions.

New focused tests first produced two assertion failures and one unhandled abort.
After repair, 28 focused component cases and all 279 web units pass. Three
temporary negative controls each reintroduced a detected defect; original source
was restored before final checks. Discovery still lists 22 ui-22 cases. Shared
workflow/minimum-count/axe gates, aliases, public-form flow and dependencies are
unchanged. `ci-repair-verification.json` records precise results and tested source
blobs. Independent review of that repair was still outstanding then. Browser qualification of head `35db89926252070db6aeca4383bfdb3ae5294b2b` is in Remaining qualification.

## Review repair — claim 6513040014

Repair base: `26bca0ea84a212247da4312dd5fe7f90509079ca`, after coordinator integration.
Independent review found that two different rows could send concurrently and the
second response could overwrite the first one-time link. The page now claims a
shared synchronous guard for create/send/resend and retains it while the result
is displayed. Done, Close and Escape acknowledge the result and release the guard.
Failure/no-link responses release it without changing stable retry behavior.
Workspace remounts remain isolated; late prior results cannot release a new
workspace's pending guard or expose their token.

| Check | Result |
| --- | --- |
| New negative controls before the repair | 4 failed, 20 passed: cross-row synchronous clicks and create/send overlap issued 2 mutations instead of 1 |
| Focused `npx --no-install vitest run tests/unit/vendor-requests.test.ts` | 25 passed, exit 0; includes three acknowledgment paths, creation serialization, rejected-row release/retry, and strengthened late-workspace coverage |
| `npm run quality` | Typecheck, lint, formatting and 276 tests in 37 files passed, exit 0 |
| `npm run build` | Production compilation/type checking and route generation passed, exit 0 |
| `npx --no-install playwright test e2e/release/ui-22.spec.ts --list` | 22 cases collected, exit 0; new two-row browser regression is included |

`invitation-serialization-verification.txt` contains actual command output. That
repair did not launch Chromium. The later browser run and screenshots are in
Remaining qualification. The unchanged HTTP alias was not rerun for this page-only repair.
The shared CI file was not edited by this worker; its current minimum is 21 and
the coordinator has been told the new count is 22.

Tested repair blobs:

| File | Git blob |
| --- | --- |
| `app/dashboard/requests/page.tsx` | `24d3b7449fe102582c21670222ec0c852701f9c4` |
| `tests/unit/vendor-requests.test.ts` | `b2e54d9832a4813e7bd6d2fa0938caa17c65bc83` |
| `e2e/release/ui-22.spec.ts` | `b9d917dced3ab28f8923cef6ada3ee629a4ae0d1` |

## Axe writer compatibility review repair

Base: `9bbc9c26f1579021d4ee39b07586d4e081bcb42a`. Independent review found that
the two `ui-22` report writers omitted the existing checker's required
`violationCount`. Both writers now emit the length of their corresponding
violations array. No checker, assertion, CI file or test-count change is included.
The coordinator's intervening `9bbc9c2` commit already requires 22 cases.

The synthetic check extracts and evaluates both actual JSON writer expressions
from the spec for 360/768/1440, then calls the unchanged
`scripts/ci/check-release-e2e-report.mjs` with synthetic Playwright/HTML fixtures.
These are report-contract controls, not browser passes or axe analysis. Temporary
fixtures stayed outside acceptance artifact directories and were deleted.

| Control | Result |
| --- | --- |
| Original writer expressions, empty violations | Checker exit 1; all six reports rejected as unusable |
| Corrected writer expressions, empty violations | Checker exit 0; six usable zero-violation synthetic reports |
| Corrected writers, injected moderate violation | Checker exit 1; all six violations still rejected |
| Corrected writers, deliberately mismatched count | Checker exit 1; all six malformed reports still rejected |
| `npm run typecheck` | Exit 0 |
| `npx --no-install eslint e2e/release/ui-22.spec.ts --max-warnings=0` | Exit 0 |
| `npx --no-install prettier --check e2e/release/ui-22.spec.ts` | Exit 0 |
| `npx --no-install playwright test e2e/release/ui-22.spec.ts --list` | 22 collected, exit 0 |
| `git diff --check` | Exit 0 |

The runner and actual checker output are preserved in
`axe-writer-compatibility-verification.txt`. Tested spec blob:
`e27ac63ea51bc2ae87e146f7121d404456d7f6d3`. This report-only fix did not repeat
the browser run. Browser, visual and axe qualification of head
`35db89926252070db6aeca4383bfdb3ae5294b2b` is in Remaining qualification.

## Original implementation results (cdf5b01)

| Check | Result |
| --- | --- |
| Baseline `npm run test:unit` | 251 passed |
| Initial `npx --no-install vitest run tests/unit/vendor-requests.test.ts` | 15 expected failures, 3 passes before implementation |
| Added off-site-link, stale clipboard acknowledgment and concurrent-dialog negative controls | Each failed for its named regression before the fix |
| Final `npm run quality` | Typecheck, lint, formatting and 271 tests in 37 files passed, exit 0; includes all 20 new controls |
| Final `npm run build` | Production compilation/type checking and route generation passed, exit 0 |
| `npx --no-install playwright test e2e/release/ui-22.spec.ts --list` | 21 cases collected; collection is not browser execution |
| HTTP alias case, filtered by `-g 'legacy bookmark'` | Original client alias: 200, failed. Final route: 307, correct same-origin Location, empty query/hash; 1 passed, exit 0 |
| Browser case, filtered by `-g 'empty requests remain'` | Launch failed, exit 1: missing `chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell`; no UI assertion executed |
| `git diff --check` | Passed |

The HTTP case used Playwright's request fixture (no browser) against a real local
Next dev server. In this environment both processes must share one execution
namespace. The server was started with `next dev --hostname 127.0.0.1 -p 33033`;
the request check used `E2E_SERVER_RUNNING=1 E2E_WEB_PORT=33033` and
`--project=chromium --no-deps --retries=0 -g 'legacy bookmark'`. The fixture name
does not imply a Chromium launch. The server was stopped after the run.

The default Playwright web-server startup initially failed on `uv_interface_addresses`;
explicit loopback binding permitted HTTP verification. An intermediate server-page
redirect still returned 200 behind the auth-loading client shell, motivating the
approved route handler. A development absolute redirect normalized the origin to
localhost; the fixed relative Location passed the unchanged same-origin assertion.
Temporary custom Next build directories initially caused generated-code lint errors;
they were removed and autoedited tsconfig/next-env restored. Final checks use normal
generated directories and unchanged lint/type configuration.

`verification.txt` preserves selected actual output. Existing npm/Vite/middleware
deprecation notices remain; they did not fail the final checks.

## Tested code identity

The original implementation commit `cdf5b01` includes these tested Git blobs.
The repair above supersedes three blobs. Final integrated-head CI IDs must be
recorded by the coordinator.

| File | Git blob |
| --- | --- |
| `app/dashboard/requests/page.tsx` | `163a27b9e6e1f27e0b2bb9d8122b260edcc33dc3` |
| `app/dashboard/vendor-requests/route.ts` | `92a23700d80743e4a1678bd49a418bcb0616348d` |
| `tests/unit/vendor-requests.test.ts` | `90ad47198c39fa5153dca33b9f00d4e62e702040` |
| `e2e/release/ui-22.spec.ts` | `417e0abebc9b970a94db88886662cc186dbc630c` |
| `e2e/requests-page.spec.ts` | `63c6e54e674132e0241b7dc7ed3e2d145459161c` |
| `e2e/vendor-response.spec.ts` | `d43492c25897147bc2078814406b27c9b3d1919c` |

## Remaining qualification

Browser qualification for head `35db89926252070db6aeca4383bfdb3ae5294b2b` is
recorded in `ci-qualification.json`. The command is `npx playwright test
e2e/release/ui-22.spec.ts`, run inside the `web-release-e2e` job from `apps/web`.
That job invokes the spec with the other release candidates:

`npx --no-install playwright test <candidates including e2e/release/ui-22.spec.ts> --retries=0 --reporter=list,html,json`

The checker requires the spec at a minimum of 22 tests and reads the six
`artifacts/acceptance/TC-15-024/axe-*.json` reports after deleting any checkout
copies. Both logs print `ui-22.spec.ts: 23 passed, 0 failed, 0 skipped, 0 flaky`,
then the six reports at 0 violations, then `playwright exit 0; axe check exit 0`.

| Event | Run | build job | web-release-e2e job | Result |
| --- | --- | --- | --- | --- |
| push | [42905431313](https://github.com/Johnathan-u/trust-copilot/actions/runs/42905431313) | 130142072405 | 130142071167 | success |
| pull_request | [42905467898](https://github.com/Johnathan-u/trust-copilot/actions/runs/42905467898) | 130142198970 | 130142199308 | success |

Environment on both `web-release-e2e` jobs: Ubuntu 26.04.1 LTS, runner image
`ubuntu-26.04` version `20261101.186.1`, Node v24.22.1 from `apps/web/.nvmrc`,
npm 11.19.1, Playwright 1.64.1. The Chromium cache hit, so the log does not
reprint the browser build id. The six axe reports are
`axe-dialog-{360,768,1440}.json` and `axe-list-{360,768,1440}.json`, each
`0 violations`. The spec has no required skip. The commit that writes this
record is later than `35db899` and does not change product code or
`e2e/release/ui-22.spec.ts`.

### Screenshots

Regenerated locally from product tree `d853ce07559a2fb9e61399aaf5aa58ed2116eef2`
(parent of the screenshot commit; no product change) and committed in
`35db89926252070db6aeca4383bfdb3ae5294b2b`. Command, from `apps/web`, using
`apps/web/playwright.config.ts` with `CI=true` and `--retries=0`, the same config
the `web-release-e2e` job loads:

`npx --no-install playwright test e2e/release/ui-22.spec.ts --retries=0`

Local result: Playwright 1.64.1, Node v24.22.1, exit 0, 23 passed. There is no
Actions run id for these pixels. They were not downloaded from
`playwright-html-report`. Each file is a non-blank RGB render of the synthetic
outbound-requests fixture (`vendor@example.com` and a repeated example address)
at the CSS width in its name and viewport height 900.

| File | Actions run id | SHA | Width |
| --- | --- | --- | --- |
| `screenshots/requests-list-360.png` | none (local regeneration) | `35db89926252070db6aeca4383bfdb3ae5294b2b` | 360 |
| `screenshots/requests-list-768.png` | none (local regeneration) | `35db89926252070db6aeca4383bfdb3ae5294b2b` | 768 |
| `screenshots/requests-list-1440.png` | none (local regeneration) | `35db89926252070db6aeca4383bfdb3ae5294b2b` | 1440 |
| `screenshots/requests-dialog-360.png` | none (local regeneration) | `35db89926252070db6aeca4383bfdb3ae5294b2b` | 360 |
| `screenshots/requests-dialog-768.png` | none (local regeneration) | `35db89926252070db6aeca4383bfdb3ae5294b2b` | 768 |
| `screenshots/requests-dialog-1440.png` | none (local regeneration) | `35db89926252070db6aeca4383bfdb3ae5294b2b` | 1440 |

The two legacy full-stack specs were updated and type-checked during the original
work and were not executed against a database/API stack. Synthetic UI fixtures
prove control paths only and do not qualify provider delivery or persistence.
Independent acceptance is outstanding. The workflow minimum for this spec remains
22, from commit `9bbc9c2`.
