# TC-14-006: release spec run at the accepted commit

This record is for `apps/web/e2e/release/responsive-shell.spec.ts` at the commit where TC-14-006 is accepted. The coordinator wrote it from the CI job log. It adds the command line that the "current" block in `evidence.json` and `evidence.md` doesn't state.

## Commit and run

- Commit: `354166555acab43576a4e2261eaafbfa8f60cfc9`. This is master, the squash merge of #217 from head `8304d1e`; the trees are identical.
- Run: CI push run [42928125079](https://github.com/Johnathan-u/trust-copilot/actions/runs/42928125079).
  - `web-release-e2e` job [130219704992](https://github.com/Johnathan-u/trust-copilot/actions/runs/42928125079/job/130219704992) ran 2026-11-11T00:02:08Z to 00:10:14Z, `success`.
  - `build` job 130219705467 also succeeded.

## Command

From `apps/web`, the release step runs every required release spec in one Playwright invocation with no retries, then runs the report and axe checker:

```
npx --no-install playwright test <required release specs, including e2e/release/responsive-shell.spec.ts> --retries=0 --reporter=list,html,json
node ../../scripts/ci/check-release-e2e-report.mjs --report test-results/release-e2e.json \
  --require-spec e2e/release/responsive-shell.spec.ts ... --axe-dir ../../artifacts/acceptance/TC-14-006 ...
```

Before the run, the job deletes the committed `TC-14-006/axe-*.json`, so a stale report can't pass the gate. Both commands exited 0 (log line: `playwright exit 0; axe check exit 0`).

## Environment

- Runner image: GitHub-hosted `ubuntu-26.04`, version 20261101.186.1
- Node v24.22.1
- Playwright 1.64.1 (Chromium)
- Server: `next dev`, started by the Playwright `webServer`

## Totals

- All release specs: 259 passed.
- `responsive-shell.spec.ts`: 8 passed, 0 failed, 0 skipped, 0 flaky.
- Axe: all 14 `TC-14-006/axe-*.json` reports have 0 violations. That covers auth dark/light at 360-closed, 360-open, 768 and 1440, and public-login dark/light at 360, 768 and 1440.
- Screenshot artifact: `responsive-shell-screenshots`, ID 13814998014.

## Not covered

7 of the 16 committed PNGs show the Next.js dev "1 Issue" badge. It comes from a hydration mismatch on `<html data-theme>`, and is tracked as follow-up TC-14-006c.
