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

## CI fixture and locator repair (2026-10-30)

Repair base: `253ecc463f582e94a5222d9e1b6359e81518cdbd` (PR #111).
Tested spec blob: `44dadfd8f34bfbc3c95b87bdf937ced34a42a0d5`.

The rejected mark-one/mark-all cases used a page-wide alert locator, which also
matched unrelated alert regions. The helper now follows the notification bell's
existing `aria-controls` relationship to its panel. Each rejected mutation must
show that panel's alert with the expected `forbidden` (403) or `server` (500)
failure kind, while all original unread-row and badge checks remain in place.

The admin dashboard also requests `/api/dashboard/cards/allowed-routes`. The
generic empty-object fallback omitted `routes`, causing `CardFormModal` to throw
at `allowedMeta.routes[0]`. Its fixture now supplies the four existing metadata
arrays (`routes`, `icons`, `sizes`, `visibility_scopes`), matching the API contract
and other release fixtures. The helper verifies the Dashboard heading and its
empty shortcuts state before opening the inbox.

Fresh local checks used Node 24.22.1 and unchanged locked dependencies:

| Check | Observed result |
| --- | --- |
| `npx --no-install prettier --check e2e/release/notification-inbox.spec.ts` | passed |
| `npx --no-install eslint e2e/release/notification-inbox.spec.ts --max-warnings=0` | exit 0 |
| `npm run typecheck` | exit 0 |
| `npm run test:unit -- tests/unit/notifications-panel.test.ts` | 8 passed |
| `npx --no-install playwright test e2e/release/notification-inbox.spec.ts --list` | all 7 existing scenarios discovered |
| `npx --no-install playwright install chromium --only-shell` | failed: downloaded archive was truncated or not a ZIP |
| Direct `chromium.launch()` preflight | blocked: chromium_headless_shell-1248 executable absent |
| `git diff --check` | passed |

No browser execution pass is claimed for this repair. The seven scenarios and
minimum-seven-tests CI gate are unchanged; this commit changes only the browser
spec and this evidence. Independent review and all four exact-final-head CI
checks remain required before merge.
