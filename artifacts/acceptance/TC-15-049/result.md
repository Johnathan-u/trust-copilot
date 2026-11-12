# TC-15-049 browser evidence

Command, from `apps/web`:

```
npx playwright test e2e/release/screen-deals.spec.ts --retries=0
```

Local environment: Linux, Node 24.22.1, npm 11.19.1, Playwright 1.64.1.
The complete spec exited 0 with **62 passed, 0 failed, 0 skipped, 0 flaky** (39.1s).
After that run, the links screenshot was moved to the top of the panel. The three
`links and risk keyboard focus and accessibility` cases were run again and passed,
and they rewrote the screenshots and axe JSON in this directory.

Screenshots, from that browser run:

- `screenshots/deals-list-360.png`
- `screenshots/deals-list-768.png`
- `screenshots/deals-list-1440.png`
- `screenshots/deals-links-360.png`
- `screenshots/deals-links-768.png`
- `screenshots/deals-links-1440.png`

Axe JSON here is `axe-list-{360,768,1440}.json` and `axe-links-{360,768,1440}.json`.
Each file has `violationCount` 0 and ends with a newline.
The existing CI axe step still writes `axe-list-*.json` and `axe-dialog-*.json`
under `artifacts/acceptance/TC-15-049a`. This directory does not replace that path.

Focused unit checks in `apps/web` for `lib/dealConsumer.test.ts` and
`tests/unit/deals-page.test.ts`: 93 passed. No backend files changed, so pytest
totals come from the `build` job below.

## CI

Recorded after `build` and `web-release-e2e` on the push and pull_request events
for the commit that contains these screenshots.
