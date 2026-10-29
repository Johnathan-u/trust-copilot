# Control library and detail evidence

Local tested commit: `ccb2be1a52ce70350841c9d8a83d7caa4eeb17e9`.
Published code commit: `7a3db78f482489625bf335c4707a150440058ca4`.
Both have identical Git tree `9a5092b9c90cf27e8e7dfffcc5f0fb139889bf06`.
GitHub git-data publishing changes commit metadata; the branch preserves the
original base, an implementation commit, a pure master merge, and review fixes.
No claim is made that browser interaction was verified locally.

Environment: Linux x86_64, Node 24.22.1, npm 11.9.0; locked `npm ci --ignore-scripts`.
No provider calls or database writes. HTTP fixtures are synthetic and do not
qualify real catalog rights or integrated backend acceptance.

## Executed checks

From `apps/web`:

| Command | Exit | Result |
| --- | --- | --- |
| `npm run typecheck` | 0 | Type generation and TypeScript pass |
| `npm run lint` | 0 | Zero lint errors/warnings |
| `npm run test:unit` | 0 | 26 files, 170 tests passed (existing suite) |
| `npm run build` | 0 | Production build succeeded |
| `npx playwright test --config=playwright.local.config.ts e2e/release/screen-controls.spec.ts -g 'route serves'` | 0 | 1 request-only test passed |

The request-only test first failed with expected 200 / actual 404 before the
route existed. The local uncommitted Playwright config only sets an explicit
127.0.0.1 hostname because interface discovery is blocked in this container.
It is not shipped. The supplied browser spec is now in CI's explicit spec list.

## Pending qualification and known limitations

- Full `screen-controls.spec.ts` browser run, 360/768/1440 screenshots, keyboard
  and axe results: pending exact-head CI. Local Playwright Chromium download
  returned truncated/empty archives; no interactive browser test is reported as
  passed, and no screenshot/axe artifact is claimed present.
- Framework activation: the current API blocks every production catalog pending
  rights clearance. The UI shows that state; no licensed activation is qualified.
- Sidebar discovery entry awaits #75 and Coordinator notice. No shared UI changed.
- Page-local links and beforeunload guard dirty edits. Browser Back and workspace
  switching are accepted follow-up TC-14-014 under Coordinator ruling 6503678126.
- Member names are admin-only; nonadmins see team / assigned-member labels.
  Owner removal is not offered because the current compliance PATCH ignores null.
- Backend evidence responses provide linked-item metadata, not source-content
  preview. This page does not invent a download or source-preview contract.

## Independent review

A separate read-only reviewer found three issues. Owner-only PATCH now omits
unchanged lifecycle. Evidence verification now reloads freshness from GET and
preserves confirmed mutation plus explicit unknown freshness if that read fails.
The shared navigation issue was ruled on by the Coordinator as TC-14-014.
New browser regression cases are present; their execution is pending CI.

## First CI feedback

At `5c80adbfe7a690fe0eb54a86cef3122b08dc4f61`, the browser suite ran: 57 passed, 7 failed. Six failures exposed an ambiguous Owner field label, now given an explicit accessible name; one assertion matched unrelated global alert regions, now scoped to the page. The build job passed lint, formatting and 170 unit tests, then rejected evidence-log whitespace; logs are normalized without changing recorded outcomes. After these fixes, local typecheck and scoped ESLint passed. Full exact-head CI is still required.
