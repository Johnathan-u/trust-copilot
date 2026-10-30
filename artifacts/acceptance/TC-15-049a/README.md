# TC-15-049a local implementation evidence

Claim: [#85 comment 6513665053](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6513665053).
Base: `91db7baf9ae252b2fb11688aae92c663318cb0c6`.
Branch: `codex/TC-15-049a-deals-ui`. The coordinator receives the exact local commit and tree separately; no worker publication or merge occurs.

The child implements only local deals list/create/edit using the merged #96 contract. See [the child release ticket](../../../docs/release/tickets/TC-15-049a.md) for behavior, API constraints and explicitly open parent gates.

Environment: Node 24.22.1, npm 11.9.0, Next 16.4.3, Playwright 1.64.1, Vitest 5.0.5. Locked existing web dependencies were reused from the sibling worktree. No manifest or lockfile changed. Commands run from `apps/web` unless otherwise specified.

| Check                                                                                                                                            | Result                                                                                  |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| New page tests before page implementation                                                                                                        | Failed to resolve the not-yet-created page; not a runtime regression claim              |
| `vitest run lib/dealConsumer.test.ts` before parser corrections                                                                                  | 8 failed / 6 passed: invalid ID/date/range acknowledgments were accepted                |
| `vitest run tests/unit/deals-page.test.ts lib/dealConsumer.test.ts` after implementation                                                         | 46 passed: 32 page controls plus 14 consumer controls                                   |
| `npm run typecheck`                                                                                                                              | Passed on the final page, consumer and test source                                      |
| `npm run lint`                                                                                                                                   | Passed on the final page, consumer and test source                                      |
| `npm run format:check`                                                                                                                           | Passed after correcting one initial browser-spec formatting failure                     |
| `npm run test:unit`                                                                                                                              | 38 files / 297 tests passed on the final source                                         |
| `npm run build`                                                                                                                                  | Passed; `/dashboard/deals` appears in generated routes                                  |
| `playwright test e2e/release/screen-deals.spec.ts --list`                                                                                        | 31 tests collected; collection is not browser qualification                             |
| `E2E_SERVER_RUNNING=1 playwright test e2e/release/screen-deals.spec.ts --project=chromium --no-deps --retries=0 --grep 'accessibility at 360px'` | Failed at browser launch before executing the test body: Chromium headless shell absent |
| `git diff --check`                                                                                                                               | Passed                                                                                  |

The final focused controls cover strict-mode cancellation, complete-vs-malformed/foreign list responses, session reads and admin-only UI writes, exact maximal money, explicit currency, invalid decimal strings, retained input for 403/404/409/422/500 and network uncertainty, synchronous duplicate submissions, stable retry keys, changed-payload keys, wrong-record/workspace acknowledgments, reload failure after save, legacy unknown currency, unsupported null-clearing, discard confirmation, unload warning, late workspace reads/writes, and permission revocation while saving.

The browser suite adds realistic auth/shell route fixtures, authoritative reloads, role cases, failure/retry controls, an already-in-flight workspace switch racing a save, and 360/768/1440 keyboard/focus/overflow/axe/screenshot checks. Browser mocks qualify UI control paths only. Axe report writers include `violationCount === violations.length`; the tests require an empty violations array. No screenshots or axe artifacts have been fabricated. The missing executable is `/root/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell`.

Remaining child gates: independent review, coordinator-owned nav/CI integration, actual browser evidence, exact final-head `build` and `web-release-e2e` on both push and pull_request. Full TC-15-049, CRM/provider and linked-risk gates remain open. No backend/database/provider qualification is claimed by this frontend child.
