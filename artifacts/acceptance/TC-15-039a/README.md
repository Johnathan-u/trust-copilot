# TC-15-039a local acceptance evidence

Base: `c2ac170f2a1572811342af67abfa4e703b14a628`.
Branch: `codex/TC-15-039a-incoming-ui`.
Environment: Node 24.22.1; repository-locked frontend packages reused from the
existing sibling checkout. No dependency or browser upgrade/install was made.
All API responses in the new tests are synthetic. No live provider was contacted.

## Executed checks

Commands run from `apps/web`:

| Command                                                                                 | Result                                                                                                                                       |
| --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run test:unit -- lib/trust-request-consumer.test.ts lib/app-navigation.test.ts`    | 29 passed across 2 files                                                                                                                     |
| `npm run test:unit`                                                                     | Exit 0: 281 passed / 38 files (`local-unit.txt`)                                                                                             |
| `npm run typecheck`                                                                     | Exit 0 (`local-typecheck.txt`)                                                                                                               |
| `npm run lint`                                                                          | Exit 0 (`local-lint.txt`)                                                                                                                    |
| `prettier --check` on the six changed frontend files                                    | Passed                                                                                                                                       |
| `npx playwright test e2e/release/screen-trust-requests.spec.ts --list`                  | 22 cases collected; execution is not implied                                                                                                 |
| `npx playwright test e2e/release/screen-trust-requests.spec.ts --workers=1 --retries=0` | Exit 1 before test execution: local Next server startup failed, then the configured 120-second startup deadline elapsed                      |
| `npm run build`                                                                         | Exit 1: Turbopack refuses the temporary dependency symlink outside its workspace root (`local-build-blocker.txt`); CI build remains required |
| Standalone locked `chromium.launch({headless:true, timeout:10000})` diagnostic          | Executable absent; no browser test or screenshot/axe result claimed                                                                          |

The default Next dev startup calls `os.networkInterfaces()`, which fails here with
`uv_interface_addresses returned Unknown system error 1`. Inspecting the installed
server confirmed an explicit localhost hostname avoids that enumeration. Chromium
was independently found absent at the locked Playwright executable location, so
further server diagnostics would not qualify browser behavior. No browser or
locked dependency installation/change was attempted. See `local-browser-blocker.txt`.

The initial consumer tests observed 9 failures/1 pass, then 10 passes. Rendered
screen tests observed 10 failures/10 passes with the placeholder screen, then 20
passes. Navigation and missing-reply refresh controls observed 2 failures/23 passes,
then 25 passes. Later unconfirmed-draft, lost-send-response and unsaved-text tests
pass in the final suite. These are component/control-path checks, not backend
integration or provider evidence.

## Required remaining evidence

Independent review and exact-final-head push/PR build and web-release-e2e checks
are pending. The coordinator must include the new 22-case browser spec and fresh
axe evidence gates. Viewport tests write sanitized axe summaries with integer
`violationCount === violations.length` and screenshots under this directory;
none are fabricated when browser execution is unavailable.

All four parent gates remain: permitted assignee-options/picker, owner/viewer
principal semantics, integrated real API/browser qualification, and live provider
delivery qualification. Parent TC-15-039 and TC-18-001 remain open. This change makes
no claim of recipient delivery, automatic resend, complete assignment UI or full
incoming Trust qualification.

## Internal-note contract repair

Read-only real-API acceptance intake found that the backend uses `internal_note`,
while the initial consumer incorrectly expected `internal`. This rejected a whole
notes response containing an internal note. The fixture was independently produced
by calling the real `_note_to_dict` serializer on a synthetic `TrustRequestNote`
using `NOTE_TYPE_INTERNAL`; no database, API response mock or backend edit was used
to derive it. The resulting literal fields are recorded in the focused unit and
browser regression fixtures, including nullable author/approval/delivery fields.

Before the repair, the backend-derived fixture caused two failures with 23 passes
in the focused consumer file. The corrected parser and page render internal notes
as read-only content alongside actionable replies; the wrong `internal` value is
rejected. After repair: 29 focused tests passed (consumer plus navigation), full
unit suite 281 passed / 38 files, typecheck passed, focused lint passed, 22 browser
cases collected. The added browser case still requires Chromium execution.
All four parent gates and earlier local browser/build limitations remain unchanged.
