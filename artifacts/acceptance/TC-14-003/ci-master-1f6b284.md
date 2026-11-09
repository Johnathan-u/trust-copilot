# TC-14-003: release spec run at the accepted commit

This file records the `dialog-toast.spec.ts` run at the commit where TC-14-003 was accepted, as the definition of done requires. It was written by the coordinator from the CI job log. GitHub deletes CI logs and artifacts after their retention period: the artifacts expire on 2026-11-23. That is why the record is kept here as well.

## Commit and run

- Commit: `1f6b28486e79a31367c0b34f55f6cafdf74ae6df` (master, the squash merge of #190; reviewed head `15058e7`).
- Run: CI push run [42543202478](https://github.com/Johnathan-u/trust-copilot/actions/runs/42543202478), job `web-release-e2e` [128922496296](https://github.com/Johnathan-u/trust-copilot/actions/runs/42543202478/job/128922496296). It started 2026-11-09T01:00:27Z and finished 01:08:25Z, with conclusion `success`.
- The `build` job in the same run (128922495971) also succeeded.

## Command

From `apps/web`, the release step runs every release spec that exists, in one Playwright invocation, with no retries:

```
npx --no-install playwright test <release specs, including e2e/release/dialog-toast.spec.ts> --retries=0 --reporter=list,html,json
node ../../scripts/ci/check-release-e2e-report.mjs --report test-results/release-e2e.json \
  --require-spec e2e/release/dialog-toast.spec.ts ...   # plus the other required specs and --axe-dir gates
```

The step fails if Playwright or the report checker exits non-zero. Both exited 0.

## Environment

- Runner image: GitHub-hosted `ubuntu-26.04`, version 20261101.186.1
- Node: v24.22.1
- Server: `next dev`, started by the Playwright `webServer` in `apps/web/playwright.config.ts`. The job has no build step and does not set `E2E_SERVER_RUNNING`.
- Playwright 1.64.1 (Chromium), from the log
- Next.js 16.4.3 and @axe-core/playwright 4.14.0, from `apps/web/package-lock.json` at this commit (not printed in the log)

## Totals

- All release specs: 253 passed, 0 failed (6.0 min).
- `dialog-toast.spec.ts`: 8 passed, 0 failed, 0 skipped, 0 flaky. The tests:
  - `:94` traps focus, restores it, and announces toasts without stealing the field
  - `:192` reduced motion removes the toast transition
  - `:202` an unknown theme query keeps the default dark theme
  - `:216` the notifications panel is a disclosure popover
  - `:274` persistent regions receive toast text, and a rejected confirm announces an error
  - `:323` info toasts leave after 4000 ms and action toasts stay
  - `:353` dark, and again light: dialogs and toasts have no axe violations at 360, 768 and 1440
- Other specs that cover this ticket:
  - `screen-trust-requests.spec.ts`: 30 passed
  - `ui-22.spec.ts`: 23 passed
  - each with 0 failed, 0 skipped, 0 flaky

## Accessibility and visual evidence

- **Axe at this commit:**
  - In this run, the axe tests at `:353` passed for dark and light at 360, 768 and 1440 px.
  - `screen-trust-requests.spec.ts` also wrote the three trust-switch reports.
  - CI artifact `dialog-toast-axe-json` (ID 13642656954, expires 2026-11-23) holds all 21 reports, each with 0 violations.
- **Committed axe reports** in this folder (each shows 0 violations):
  - `axe-{dialog,confirm,toast}-{dark,light}-{360,768,1440}.json`: git last changed these in `58b8c87` (#21). The note at `92b0c3e:artifacts/acceptance/TC-14-003/evidence.md` says a local run at `d9fac72` regenerated them. The files carry no SHA of their own, so that note is the only source for the `d9fac72` attribution.
  - `axe-trust-switch-{360,768,1440}.json`: a local run at `b923a28ba71e52c5c6e204303035747833b3dc32`.
- **Committed screenshots:**
  - `screenshots/{dialog,confirm}-{dark,light}-{360,768,1440}.png`: changed in `d9fac72`, by a local production `next start` build. The environment is recorded in the `92b0c3e` note: Linux 6.12, Node v24.22.1, Next.js 16.4.3, Playwright 1.64.1 with chromium-1248, @axe-core/playwright 4.14.0.
  - `screenshots/trust-switch-{360,768,1440}.png`: run at `b923a28b…` with `next dev`.
- **Nothing these depend on changed afterwards.** Comparing `d9fac72..15058e7` in git shows no changes in `apps/web/components`, `apps/web/lib`, `apps/web/app/design-dialogs` or `dialog-toast.spec.ts`. Comparing `b923a28b..15058e7` shows none in the trust-requests page, `screen-trust-requests.spec.ts` or those components. This is a fact from git, not a finding of the review.
- **Not covered:**
  - There are no toast screenshots.
  - There is no visual evidence for the dashboard pages whose messages changed under AC2. No review asked for either; AC2 is covered by the tests and the reviews.
