# TC-14-003 acceptance evidence

Synthetic data only. Screenshots and axe output contain no credentials, customer documents or personal data.

This note does not claim that CI `build` is green. Head `7bbfb7c` failed `build` on push run 42324149162 and pull_request run 42324166892 because `test_trust_requests_browser.py` still accepted a native confirm. The review fix updates that acceptance. This machine has no Docker and no PostgreSQL, so that backend-driven browser test was not run here. CI has to show whether `build` passes.

## Dialog and toast spec

Recorded against implementation commit `d9fac72ea5da5060e60ee2b4e2a717daf25a77c8`. Not re-run for the review fix, which does not change `dialog-toast.spec.ts` or the shared dialog and toast primitives. Re-running it would overwrite the production screenshots below.

```bash
cd apps/web
npx playwright test e2e/release/dialog-toast.spec.ts --retries=0
```

- Exit status: 0
- Tests: 8 passed, 0 failed, 0 skipped
- Duration: 33.6s
- Server: `next start` production build on `http://127.0.0.1:3000`
- Node: v24.22.1
- npm: 11.19.1
- Next.js: 16.4.3
- Playwright: 1.64.1
- Chromium: Playwright build chromium-1248
- @axe-core/playwright: 4.14.0
- OS: Linux 6.12.113+ x86_64

Axe on `#dialog-showcase` and `#tc-toast-live`: 0 violations for dialog, confirm and toast, dark and light, at 360, 768 and 1440 CSS px (18 reports). No critical or serious violation. Screenshots: `screenshots/{dialog,confirm}-{dark,light}-{360,768,1440}.png`.

## Review-fix runs

These ran on the working tree that contains the review fixes, before that commit's SHA existed. Environment: same OS, Node, npm, Playwright and Chromium. Server: Playwright `next dev` on `http://127.0.0.1:3000` (the dev overlay was not in the trust-switch screenshots).

```bash
cd apps/web
npx playwright test e2e/release/screen-trust-requests.spec.ts --retries=0
```

- Exit status: 0
- Tests: 30 passed, 0 failed, 0 skipped
- Duration: 26.9s
- Includes Tab wrap from the last control of "Leave this page?" and the "Discard unsaved reply text?" switch dialog.

```bash
cd apps/web
npx playwright test e2e/release/ui-22.spec.ts -g "delayed create|rejected create|long content, keyboard" --retries=0
```

- Exit status: 0
- Tests: 5 passed, 0 failed, 0 skipped (plus the two trust-request tests in the same 7-test invocation)
- The create dialog's status region is empty before the result, then reads "Your request has been created."
- A 422 create leaves `role="alert"` inside the dialog and does not move focus onto that alert.

The switch dialog axe reports are `axe-trust-switch-{360,768,1440}.json`. Each `violationCount` is 0. Screenshots: `screenshots/trust-switch-{360,768,1440}.png`. The same files are written under `artifacts/acceptance/TC-14-003a/`.

## Not run

```bash
cd apps/api
TC_REQUIRE_DB=1 TC_REQUIRE_WEB_TOOLCHAIN=1 python -m pytest tests/release/test_trust_requests_browser.py -q
```

Not run. This environment has no Docker and no PostgreSQL, so `DATABASE_URL` is unset. The Playwright file that pytest launches, `apps/web/e2e/integration/trust-requests.acceptance.ts`, now clicks "Discard and open" in the in-page alertdialog instead of accepting `window.confirm`. That is necessary for the test and is not a skip. It is not a local pass.

`test_health_probes.py` was not changed. The earlier pull_request failure of that test was left as an unrelated flake.

Grok (worker). The implementer does not accept this result.
