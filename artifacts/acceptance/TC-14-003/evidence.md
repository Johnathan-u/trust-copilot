# TC-14-003 acceptance evidence

Synthetic data only. The showcase, screenshots and axe output contain no credentials, customer documents or personal data.

## Latest run

Tested commit: `d16b472d305bea8d26d4c29964ad3cc9c8536d54` on branch `tc/web/TC-14-003`.

That commit is the disclosure-popover and toast-timing change (`87a4420`) plus the exact Playwright name match. This note was added afterwards and does not change the suite. The branch includes the unmerged TC-14-001 commits from PR #6. `origin/master` at the time of the run was `f72def39245abf5cb46c7b3693f687114fa4b1b5`, which is already an ancestor. No merge was required.

### Environment

- OS: Linux 6.12.94+ x86_64
- Node: v22.23.4
- npm: 10.9.9
- Next.js: 14.2.15
- Vitest: 2.1.9
- Playwright: 1.58.2 (`apps/web/node_modules`)
- Chromium: Playwright build chromium-1208
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web`

### Commands and results

```bash
cd apps/web
npm run test:unit
```

- Exit status: 0
- Test files: 5 passed
- Tests: 23 passed, 0 failed, 0 skipped
- Includes `lib/dialog.test.ts`, `lib/disclosure.test.ts` and `lib/toast.test.ts`
- Toast policy: success, info and warning without an action dismiss at 4000ms. Any severity with an action button, and every error, returns `null`.

```bash
cd apps/web
npx playwright test e2e/release/dialog-toast.spec.ts --retries=0
```

- Exit status: 0
- Tests: 7 passed, 0 failed, 0 skipped
- Duration: 34.7s
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
