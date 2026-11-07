# TC-14-003 acceptance evidence

Synthetic data only. The showcase, screenshots and axe output contain no credentials, customer documents or personal data.

## Latest run

The dialog and toast behavior was already on master. This run is the working tree that closes the remaining call-site gaps (incoming Trust request confirms, in-dialog error alerts, Gmail and vendor-request descriptions) and refreshes the screenshots. The commit SHA below is the implementation commit. The evidence note does not change the suite.

Tested commit: `d9fac72ea5da5060e60ee2b4e2a717daf25a77c8` on branch `tc/TC-14-003-dialog-focus`. Base master: `10220265182a872f02b13ec96a2d6a6fb9714a1d`.

### Environment

- OS: Linux 6.12.113+ x86_64
- Node: v24.22.1 (`apps/web/.nvmrc`)
- npm: 11.19.1
- Next.js: 16.4.3 (`next start` production build, reused on `http://127.0.0.1:3000`)
- Playwright: 1.64.1 (`apps/web/node_modules`)
- Chromium: Playwright build chromium-1248
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web`

### Command and result

```bash
cd apps/web
npx playwright test e2e/release/dialog-toast.spec.ts --retries=0
```

- Exit status: 0
- Tests: 8 passed, 0 failed, 0 skipped
- Duration: 33.6s
- No required test was skipped

The same command against `next dev` also exited 0 (8 passed, 43.1s). The committed screenshots are from the production server so the Next.js dev issue badge is not in the images.

Keyboard and announcement checks on `/design-dialogs` (synthetic records only), asserted by the spec:

- Rename dialog: focus starts on the name field, Shift+Tab and Tab wrap inside, Escape closes, focus returns to "Rename sample". The notes field is inside an `inert` ancestor while the dialog is open. The dialog name and description are exposed.
- Delete confirmation: `role="alertdialog"`, named "Delete sample record?", description includes the archive sentence, initial focus is Cancel, Escape returns focus to the trigger.
- Side panel (`placement="drawer-end"`): focus starts on the first destination, Tab wraps to Close, Escape returns to "Open side panel".
- Typing " ok" in Working notes shows a polite `status` toast and leaves the field focused. The toast is gone after the 4000ms status interval.
- Typing " err" shows an assertive `alert` toast, leaves the field focused, and is still present after the same interval. Tab reaches "Dismiss Save failed" and Enter removes it.
- Notifications bell: `aria-expanded` and `aria-controls` are set. The open panel is not a dialog and not `aria-modal`. The notes field is not inside `[inert]`. Focus is not trapped. Escape and an outside click close the panel and return focus to the bell.
- "Show info" shows a polite status toast that is gone after 4500ms.
- "Show undo" shows a success toast with an Undo button that is still visible after 4500ms. Activating Undo clears it and sets Working notes to "restored".
- `prefers-reduced-motion: reduce` computes the toast transition duration as 0s.
- An unknown `theme` query leaves the default dark theme in place.
- Font requests during the themed runs stayed on this origin. No third-party font host was requested.

Axe (`#dialog-showcase` and `#tc-toast-live`): 0 violations for dialog+status, alertdialog+error, and error toast alone, in dark and light, at 360, 768 and 1440 CSS px. Reports: `axe-{dialog,confirm,toast}-{dark,light}-{360,768,1440}.json` (18 files, each `violationCount` 0). No critical or serious violation.

Screenshots, with the dialog open and a toast on screen: `artifacts/acceptance/TC-14-003/screenshots/{dialog,confirm}-{dark,light}-{360,768,1440}.png`. The same files are written to `artifacts/acceptance/TC-14-003a/`.

### Additional checks

```bash
cd apps/web
npx playwright test e2e/release/screen-trust-requests.spec.ts -g "unsaved reply leave" --retries=0
```

- Exit status: 0
- Tests: 1 passed, 0 failed, 0 skipped
- The unsaved-reply leave dialog is an alertdialog with a description, Cancel is focused, Tab stays on the confirm control, Escape restores the Documents link and the reply text, and "Discard and leave" navigates to Documents.

```bash
npx playwright test e2e/release/ui-22.spec.ts -g "delayed create|creation exposes only the returned|simultaneous row|long content, keyboard" --retries=0
```

- Exit status: 0
- Tests: 6 passed, 0 failed, 0 skipped

`npm run build` (Next.js 16.4.3 production build, including TypeScript) exited 0. `npx eslint` on the changed pages and specs exited 0.

### Toast timing decision

Success, info and warning toasts auto-dismiss at 4000ms. A toast that includes an action button does not auto-dismiss. The timer is omitted, not paused on hover or focus, so the action has no time limit (WCAG 2.2.1 Timing Adjustable). Errors stay until the user dismisses them. `Toast` owns the single timer.

Grok (worker). The implementer does not accept this result.
