# TC-14-003 acceptance evidence

Synthetic data only. The showcase, screenshots and axe output contain no credentials, customer documents or personal data.

## Latest run

Tested commit: `4d72cdc189a8241190eb04b6c5df0429440dc00c` on branch `tc/web/TC-14-003`.

That commit merges `origin/master` (`705bdde`, the squash of PR #6, plus #36, #37, #38 and #40). Token files, design-token libraries, fonts, the design-tokens page and spec, TC-14-001 docs and evidence, `package.json` and the lockfile match that master commit. This note was added afterwards and does not change the suite.

### Environment

- OS: Linux 6.12.94+ x86_64
- Node: v24.22.1 (`apps/web/.nvmrc`)
- npm: 11.19.1
- Next.js: 16.4.3
- Vitest: 5.0.5
- Playwright: 1.64.1 (`apps/web/node_modules`)
- Chromium: Playwright build chromium-1248
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web`
- Install: `npm ci --ignore-scripts`

### Commands and results

```bash
cd apps/web
npm run lint
npm run format:check
npm run typecheck
npm run test:unit
npm run build
npm audit --omit=dev --audit-level=high
```

- Each exit status: 0
- Unit test files: 13 passed
- Unit tests: 99 passed, 0 failed, 0 skipped
- Includes `lib/dialog.test.ts`, `lib/disclosure.test.ts` and `lib/toast.test.ts`
- Toast policy: success, info and warning without an action dismiss at 4000ms. Any severity with an action button, and every error, returns `null`.
- Audit: 0 vulnerabilities

```bash
cd /workspace
python3 scripts/security/secret_inventory.py tree --root .
pre-commit run --all-files
ruff check apps/api
TC_REQUIRE_WEB_TOOLCHAIN=1 python3 -m pytest apps/api/tests/release/test_web_quality.py -q --noconftest
```

- Secret tree-scan exit status: 0 (`block` 0, `review` findings only)
- pre-commit exit status: 0 (ruff, ruff-format, prettier, trailing whitespace, end-of-file, check-yaml)
- `ruff check apps/api` exit status: 0
- Web quality tests: 26 passed, including the runtime-module coverage check

```bash
cd apps/web
npx playwright test e2e/release/dialog-toast.spec.ts --retries=0
```

- Exit status: 0
- Tests: 7 passed, 0 failed, 0 skipped
- Duration: 30.7s
- No required test was skipped

Keyboard checks on `/design-dialogs` (synthetic records only):

- Rename dialog: focus starts on the name field, Shift+Tab and Tab wrap inside, Escape closes, focus returns to "Rename sample". The notes field is inside an `inert` ancestor while the dialog is open. The dialog name and description are exposed.
- Delete confirmation: `role="alertdialog"`, named "Delete sample record?", description includes the archive sentence, initial focus is Cancel, Escape returns focus to the trigger.
- Side panel (`placement="drawer-end"`): focus starts on the first destination, Tab wraps to Close, Escape returns to "Open side panel".
- Typing " ok" in Working notes shows a polite `status` toast and leaves the field focused. The toast is gone after the 4000ms status interval.
- Typing " err" shows an assertive `alert` toast, leaves the field focused, and is still present after the same interval. Tab reaches "Dismiss Save failed" and Enter removes it.
- Notifications bell: `aria-expanded` is false while closed and true while open, and `aria-controls` is `sample-notifications`. The open panel is not a dialog and not `aria-modal`. The notes field is not inside `[inert]`, and no `[inert]` element is present. Shift+Tab from inside the panel reaches the bell. Tab from "Notification settings" reaches "Page help", so focus is not trapped. Escape closes the panel and returns focus to the bell. A click on Working notes closes the panel and returns focus to the bell.
- "Show info" shows a polite status toast that is gone after 4500ms.
- "Show undo" shows a success toast with an Undo button. The toast is still visible after 4500ms. Activating Undo clears it and sets Working notes to "restored".
- `prefers-reduced-motion: reduce` computes the toast transition duration as 0s.
- An unknown `theme` query leaves the default dark theme in place.
- Font requests during the themed runs stayed on this origin. No third-party font host was requested.

The notifications request from the showcase returns connection refused for the API on port 8000. The panel still renders its disclosure shell, which is what the keyboard and outside-click checks use.

Axe (`#dialog-showcase`): 0 violations for dialog+status, alertdialog+error, and error toast alone, in dark and light, at 360, 768 and 1440 CSS px. Reports: `axe-{dialog,confirm,toast}-{dark,light}-{360,768,1440}.json` (18 files, each `violationCount` 0).

Screenshots, with the dialog open and a toast on screen: `artifacts/acceptance/TC-14-003/screenshots/{dialog,confirm}-{dark,light}-{360,768,1440}.png`.

While a dialog is open the toast remains visually present and is `inert`, so it is not a second focus stop. The toast-only axe pass covers the announcement when it is in the accessibility tree.

### Toast timing decision

Success, info and warning toasts auto-dismiss at 4000ms. A toast that includes an action button does not auto-dismiss. The timer is omitted, not paused on hover or focus, so the action has no time limit (WCAG 2.2.1 Timing Adjustable). Errors stay until the user dismisses them. `Toast` owns the single timer. The review page no longer uses 5000ms or 8000ms timers.
