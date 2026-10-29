# TC-19-010a local evidence

Base: `059681048383c4ed8a8f1708f70359683850f406` (#75).
Tested implementation: `ed01f2ac11afb7cc4c2cfcfe04efe379928c1b57`.
Tree: `5ffdcca678ed931611ba4b66ca81fa40c51ddd4f`.

From `apps/web`, with Node 24.22.1 and the existing locked dependencies:

| Check | Observed result |
| --- | --- |
| `npm run test:unit -- tests/unit/notifications-panel.test.ts`, before implementation | 8 failed: page count replaced total; rejected writes changed rows; network rejection was unhandled; accepted writes/reopening did not refresh count |
| Same targeted regression command after implementation | 8 passed |
| `npm run test:unit` | 198 passed, 30 files |
| `npm run lint` | exit 0 |
| `npm run typecheck` | exit 0 |
| `npm run build` | exit 0 |
| Prettier check of changed web files | passed |
| `npx --no-install playwright test e2e/release/notification-inbox.spec.ts --list` | 7 cases discovered |
| Chromium launch | blocked: executable absent at the Playwright chromium_headless_shell-1248 path |
| `git diff --check` | passed |

The eight real-component regressions cover a 25-unread/20-visible page, rejected
single/all writes, network rejection, successful single/all writes with a server
count, reopening, and a failed count refresh. A failed count refresh preserves the
last confirmed count; it does not invent zero or undo an accepted row update.

Browser cases cover the limited page at 360/1440 pixels, rejected single/all
writes, accepted single/all writes, and reopening. No local browser pass or
real-provider qualification is claimed. Existing npm proxy-configuration and Vite
configuration-format warnings were present; neither caused verification failure.

The separate CI commit adds only this spec and its minimum-seven-tests gate.
Independent review and all four final-head push/pull-request build and
web-release-e2e checks remain required before merge and consumer completion.
