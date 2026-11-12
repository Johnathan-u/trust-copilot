# TC-15-038 browser evidence

Command recorded for this ticket, from `apps/web`:

```sh
npx playwright test e2e/release/screen-jobs.spec.ts
```

CI does not run that file alone. The `web-release-e2e` job runs it inside the release list:

```sh
npx --no-install playwright test e2e/release/screen-jobs.spec.ts … --retries=0 --reporter=list,html,json
```

The checker then requires `e2e/release/screen-jobs.spec.ts` with `--min-tests 39`. That minimum was not changed.

## SHA

The run below is code commit `2ada83e861271a1ae6bc306283842c5de6884a42`. This README and the screenshots were added after that run. They do not change `screen-jobs.spec.ts`, the jobs page, or the history API.

## Runs

Both events are for that SHA. `build` and `web-release-e2e` succeeded on each.

| Event | Run | `build` job | `web-release-e2e` job |
| --- | --- | --- | --- |
| push | [43105815535](https://github.com/Johnathan-u/trust-copilot/actions/runs/43105815535) | 130808716721 | 130808716479 |
| pull_request | [43105852467](https://github.com/Johnathan-u/trust-copilot/actions/runs/43105852467) | 130808840602 | 130808840063 |

## Environment

GitHub-hosted `ubuntu-26.04`, Ubuntu 26.04.1, image `20261101.186.1`. Node `v24.22.1` (`apps/web/.nvmrc`). The job prints Playwright `Version 1.64.1` and installs Chromium with `npx --no-install playwright install --with-deps chromium`. That package's `playwright-core` browser manifest names Chrome for Testing `156.0.8078.4`.

## Result

`web-release-e2e` printed `playwright exit 0; axe check exit 0` on both runs.

`screen-jobs.spec.ts: 39 passed, 0 failed, 0 skipped, 0 flaky` on both runs.

The same job's axe checker, reading the fresh `artifacts/acceptance/TC-15-038b/axe-*.json` files, printed:

- `TC-15-038b/axe-page-360.json: 0 violations`
- `TC-15-038b/axe-page-768.json: 0 violations`
- `TC-15-038b/axe-page-1440.json: 0 violations`
- `TC-15-038b/axe-dialog-360.json: 0 violations`
- `TC-15-038b/axe-dialog-768.json: 0 violations`
- `TC-15-038b/axe-dialog-1440.json: 0 violations`
- `axe violations: 0`

The uploaded `jobs-axe-json` artifact from the push run matches that summary. Each file has integer `violationCount` 0 and `violations: []`.

`build` on both runs printed `6450 passed, 1 skipped`. The only skip is `tests/test_trust_scoring_blind.py:33`.

## Screenshots

Copied from the push run's `playwright-html-report` attachments for `jobs page and dialog keyboard/axe`. The pull_request run executed the same three viewport cases. Files are in `screenshots/`:

- `page-360.png`, `dialog-360.png` (360×900)
- `page-768.png`, `dialog-768.png` (768×900)
- `page-1440.png`, `dialog-1440.png` (1440×900)

## Visual review

At 360 px the navigation is a menu button. The job card stacks its labels, the progress bar, the charge warning, and Cancel job inside the width. At 768 and 1440 px Jobs is the current sidebar item; at 1440 px it is also the current top-bar item. The detail dialog sits on a dimmed page, keeps its title and close control, and shows a focus ring on Reload details. The page reads "2 of 5 answers generated". The dialog reads "3 of 5 answers generated", which is the detail fixture, not a second progress source. Completed time reads "Not reported" because the fixture has no completion timestamp. No storage key, raw error, or other private field is visible. The six frames show no clipped primary action and no horizontal overflow. The 1440 px sidebar is taller than the 900 px frame and scrolls inside its own region; Jobs remains visible as the current route.
