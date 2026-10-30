# TC-15-024 local acceptance evidence — 2026-10-30

Base: `35384fd1907ac9235922a74a575a1630aa0519ec`.
Branch: `codex/TC-15-024-outbound-ui`. Claims/rulings: #85 comments `6512668742`
and `6512889661`. The coordinator owns independent review, publication and merges.
All commands below run from `apps/web`, with Node v24.22.1 and the existing locked
dependencies. No dependency changes are included. Coordinator commit `26bca0e`
subsequently integrated the CI candidate/count/axe configuration.

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

`invitation-serialization-verification.txt` contains actual command output. The
configured Chromium executable remains absent; no new browser run or screenshot
is claimed. The unchanged HTTP alias was not rerun for this page-only repair.
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
`e27ac63ea51bc2ae87e146f7121d404456d7f6d3`. Browser/visual/axe qualification remains
pending; the prior application checks were not repeated for this report-only fix.

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

Twenty-one browser cases, screenshots, keyboard/Back behavior and axe outcomes are
pending. The attempted UI launch failed before assertions; no local browser pass
or visual inspection is claimed. The two legacy full-stack specs were updated and
type-checked but not executed against a database/API stack. Synthetic UI fixtures
prove control paths only and cannot qualify provider delivery or persistence.

The coordinator has added `ui-22.spec.ts` to the release candidate list, configured
stale axe artifact removal before each run, and included `artifacts/acceptance/TC-15-024`
in the axe gate. Commit `9bbc9c2` raises the minimum count to 22. The spec writes list/dialog axe JSON
and screenshots at 360/768/1440 and attaches them to the report. It contains no
required skips. Exact final-head build and web-release-e2e must pass on push and
pull_request, with independent review, before merge. This is not Done.
