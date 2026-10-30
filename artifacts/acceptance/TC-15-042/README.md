# Control library and detail evidence

Qualified implementation checkpoint: `7c8ac622e99d6385d4d83347dc5124b5a8efced4`.
Git tree: `8bf6568773c0cb9181b9aa3d71efd83d91dc61eb`.
All four required checks passed on this exact head: push run
[40924117490](https://github.com/Johnathan-u/trust-copilot/actions/runs/40924117490)
and PR run
[40924126208](https://github.com/Johnathan-u/trust-copilot/actions/runs/40924126208).

## Browser qualification

On the PR run, `web-release-e2e` job
[123624976027](https://github.com/Johnathan-u/trust-copilot/actions/runs/40924126208/job/123624976027)
ran the explicit release spec list, including `e2e/release/screen-controls.spec.ts`:
**21/21 control cases passed**, with **64/64 tests passed** across the release
suite. Playwright exit status was 0 and the axe checker exit status was 0.
The workflow uses Ubuntu, the repository-pinned Node version, locked
`npm ci --ignore-scripts`, and Playwright Chromium. The focused command is
`npx playwright test e2e/release/screen-controls.spec.ts` from `apps/web`.

The [Playwright HTML report artifact](https://github.com/Johnathan-u/trust-copilot/actions/runs/40924126208/artifacts/12919348682)
contains attachments named `library-360`, `detail-360`, `library-768`,
`detail-768`, `library-1440`, `detail-1440`, plus matching `axe-<view>-<width>`
JSON attachments. All three viewport reports have `violations: []` (identical
library/detail JSON content may be deduplicated in the archive). Before attachment,
the tests write screenshots to `artifacts/acceptance/TC-15-042/screenshots/` and
axe output to `artifacts/acceptance/TC-15-042/axe-<view>-<width>.json` on the runner.
These are retained through the HTML artifact, not a dedicated axe upload step.

The browser cases cover roles, denied/not-found/malformed reads, partial evaluation
failure, owner-only PATCH acknowledgement/rejection, dirty-link confirmation,
expired and newly stale evidence after review, partial review success, keyboard
focus and responsive containment. The library and detail screenshots were visually
inspected at 360, 768 and 1440 pixels: no layout blocker; the library table scrolls
within its container at narrow widths. No local browser execution is claimed.

## Local checkpoint and retained logs

The local logs in this directory are from commit
`ccb2be1a52ce70350841c9d8a83d7caa4eeb17e9`, published as
`7a3db78f482489625bf335c4707a150440058ca4` with identical tree
`9a5092b9c90cf27e8e7dfffcc5f0fb139889bf06`. Later product-label fixes are covered by
the exact-head CI above. Local environment: Linux x86_64, Node 24.22.1, npm 11.9.0.

| Command (apps/web)                                                                                              | Exit | Result                                |
| --------------------------------------------------------------------------------------------------------------- | ---- | ------------------------------------- |
| `npm run typecheck`                                                                                             | 0    | Type generation and TypeScript passed |
| `npm run lint`                                                                                                  | 0    | Zero errors/warnings                  |
| `npm run test:unit`                                                                                             | 0    | 26 files, 170 tests passed            |
| `npm run build`                                                                                                 | 0    | Production build succeeded            |
| `npx playwright test --config=playwright.local.config.ts e2e/release/screen-controls.spec.ts -g 'route serves'` | 0    | One request-only route test passed    |

The route test first failed with expected 200 / actual 404 before implementation.
The local hostname-only Playwright configuration is not shipped. Browser downloads
were unavailable locally; the successful browser evidence above comes from CI.
Fixtures are synthetic, with no provider calls or database writes. They do not
qualify real catalog rights or integrated backend acceptance.

## Accepted-pending limits

- AC1 licensed-framework activation remains rights-blocked by owner decision
  TC-01-007, accepted-pending in Coordinator review 6504688809. The UI shows the
  API's rights state; licensed activation is not claimed complete.
- Sidebar discovery was pending at this checkpoint. The later authorized navigation follow-up is recorded below.
- Page-local links and beforeunload guard dirty edits. Browser Back and workspace
  switching remain follow-up TC-14-014 under ruling 6503678126.
- Member names are admin-only; other roles see team / assigned-member labels.
  Owner removal is unavailable because the current compliance PATCH ignores null.
- Evidence responses provide linked-item metadata, not source-content preview.
- Per-spec CI summary and dedicated axe upload inclusion are non-blocking follow-ups
  from review 6504688809. Tests execute and attachments are in the HTML artifact.

## Independent review

A separate reviewer found owner-only PATCH, freshness refresh and shared-navigation
issues. The first two were fixed and rechecked; the navigation limit was accepted
as TC-14-014. Browser regressions subsequently passed at the checkpoint above.
The initial CI label/selector and log-whitespace failures were corrected before
that successful run. No unresolved blocking finding remains in the reviewed scope.

## Authorized evaluation-loading and CI evidence follow-up

Coordinator ruling 6505100098 authorizes this separate follow-up after #90 merged.
The library now labels evaluation as loading while the coverage request is pending,
instead of temporarily presenting an unknown result. A held-response browser case
checks the pending label and transition to the authoritative evaluation.

The existing release workflow now includes screen-controls in its per-spec summary
with a 22-case minimum, clears stale control axe files, checks the current control
axe directory, and uploads it separately. The spec emits the checker-required
violation count alongside each full violation list. No workflow triggers, retries,
checker logic, shared UI or Sidebar change. Local checks and exact-head browser
evidence will qualify this follow-up separately from the earlier #90 results.

### Follow-up local verification

Tested local code commit: `a1f18645989f1a25e32bf9a0d72cdf684552ddda`.
Tree: `9d1496a71a818669860a014a48d948c38aea0a3e`, identical to published code
commit `89bd7b9ac717443db1bbc294b3a1f114e81fef38`. The later evidence commit
adds only these records; browser qualification still requires its exact final head.

| Command (apps/web)                                               | Exit | Result                                |
| ---------------------------------------------------------------- | ---- | ------------------------------------- |
| `npm run typecheck`                                              | 0    | Type generation and TypeScript passed |
| `npm run lint`                                                   | 0    | Zero errors/warnings                  |
| `npm run test:unit`                                              | 0    | 27 files, 173 tests passed            |
| `npm run build`                                                  | 0    | Production build succeeded            |
| `npx playwright test e2e/release/screen-controls.spec.ts --list` | 0    | 22 cases discovered; discovery only   |

The `followup-*.log` files contain exact local SHA/tree and command results,
normalized for line endings/trailing whitespace only. Workflow YAML also parsed
successfully. Independent review found no blocker in the loading state, held
response regression or bounded CI evidence changes. Local Chromium is unavailable;
final browser/axe results will be recorded in the PR and #85 without rewriting
this tested-code checkpoint. Licensed activation and TC-14-014 navigation limits
from #90 remain unchanged.

## Authorized Controls navigation follow-up, 2026-10-30

Claims: #85 comments 6512147328 and 6512246459, after #75 and Coordinator notice.
Local branch: `codex/TC-15-042-controls-navigation`; base:
`af4a57f6518ca5ca9c46ba629a03eb7615651833`.

The only product change adds `Controls` → `/dashboard/controls` immediately after
Frameworks in `apps/web/lib/app-navigation.ts`. Existing consumers supply the
Sidebar, top bar and command palette. The link shares Frameworks' visibility;
there are no component, style or permission changes and no new test framework.

Environment: Node 24.22.1, npm 11.9.0. Dependencies were copied from the installed
sibling worktree after `cmp apps/web/package-lock.json ../tc-gap-provenance/apps/web/package-lock.json`
confirmed identical lockfiles. No dependency or lockfile changes.

| Command (from `apps/web`) | Exit | Result |
| --- | --- | --- |
| `npm run test:unit -- lib/app-navigation.test.ts lib/controlContract.test.ts lib/frameworkCatalog.test.ts lib/coverageConsumer.test.ts` | 0 | 4 files, 19 tests passed |
| `npm run typecheck` | 0 | Route type generation and TypeScript passed |
| `npx eslint lib/app-navigation.ts --max-warnings=0` | 0 | No lint errors or warnings |
| `npx prettier --check lib/app-navigation.ts` | 0 | Formatting passed |
| `git diff --check` (repository root) | 0 | No whitespace errors |

Existing npm proxy-configuration and Vite future-loader notices were emitted.
No browser, full production build or new exact-head CI result is claimed for this
small navigation follow-up. The earlier browser results above qualify their
recorded commits, not this change. Independent review and required final-head CI
remain with the Coordinator. Rights and TC-14-014 limits remain unchanged.
