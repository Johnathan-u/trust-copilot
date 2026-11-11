# TC-15-024a acceptance evidence

Local evidence for gating the Requests navigation item on `can_review`. Base is `dad086216f323f0caf1b39ec0eb4115515ec54eb`. The failing unit log ran the new cases against that commit's `apps/web/lib/app-navigation.ts` (blob `2aafedfe488c0ad59036c79e221d95bd2f09ab9f`). The passing unit log, the full web unit run, and the ui-22 run are this commit's tree.

Commands ran from `apps/web` with Node v24.22.1, npm 11.19.1, Vitest 5.0.5, and Playwright 1.64.1. Chromium is Playwright's Chrome for Testing 156.0.8078.4.

## Backend rule this nav follows

`require_vendor_review` is `_current_permission("can_review")` in `apps/api/app/api/routes/vendor_requests.py`. `vendor_request_service.current_permission` allows the call when that flag is true.

Builtin roles use `can_review()` in `apps/api/app/core/roles.py`:

| Role | `can_review` | `require_vendor_review` |
| --- | --- | --- |
| admin | true | allowed |
| editor | true | allowed |
| reviewer | true | allowed |

Any other role name, including viewer, is allowed only when that workspace has a custom role of the same name with `can_review` set. A principal with `can_edit` and without `can_review` is denied. The page guard uses the same flag: `permissions.can_review` from `useAuth()` (`GET /api/auth/me`).

The sidebar and the top bar now pass that same `permissions.can_review` into `appNavItemsFor`. The Requests item is `requiresReview: true`, so it is listed only when `can_review` is true.

## Criterion → evidence

| Criterion | Evidence |
| --- | --- |
| New Requests expectations fail on the previous nav filter. An editor without `can_review` still saw the link, and a reviewer with `can_review` did not. | [`unit-before.txt`](unit-before.txt). Exit 1. 2 failed, 7 passed. |
| Viewer hides Requests. Editor without review hides Requests. Editor with review shows Requests. Reviewer shows Requests. Admin shows Requests. | [`unit-after.txt`](unit-after.txt). Exit 0. 9 passed. |
| The rest of the web unit suite still passes with those five cases included. | [`unit-all.txt`](unit-all.txt). Exit 0. 49 files, 456 passed. Master CI on the base SHA reported 451 passed. |
| Editor with review sees Requests in the sidebar and the top bar, and a direct visit to `/dashboard/requests` shows the list. | [`ui-22.txt`](ui-22.txt) editor navigation case. [`screenshots/requests-nav-editor.png`](screenshots/requests-nav-editor.png). |
| Reviewer sees Requests in the sidebar and the top bar, and a direct visit shows the list. | [`ui-22.txt`](ui-22.txt) reviewer navigation case. [`screenshots/requests-nav-reviewer.png`](screenshots/requests-nav-reviewer.png). |
| Editor without review does not see Requests in the sidebar or the top bar, and a direct visit stays on the review-access denial. The list request is not sent. | [`ui-22.txt`](ui-22.txt) editor-without-review case. [`screenshots/requests-nav-editor-without-review.png`](screenshots/requests-nav-editor-without-review.png). |
| ui-22 reports the larger count with no failures. | [`ui-22.txt`](ui-22.txt). Exit 0. 26 passed. Master CI on the base SHA reported `ui-22.spec.ts: 23 passed, 0 failed, 0 skipped, 0 flaky`. |

## Commands

Failing before, master's `app-navigation.ts` and the new unit cases:

```
NO_COLOR=1 npx --no-install vitest run lib/app-navigation.test.ts --reporter=verbose
```

Passing after, same command. Exit 0.

Full web unit suite:

```
NO_COLOR=1 npx --no-install vitest run --reporter=dot
```

Exit 0. 456 passed.

ui-22, retries off, list reporter:

```
NO_COLOR=1 NEXT_TELEMETRY_DISABLED=1 npx --no-install playwright test e2e/release/ui-22.spec.ts --retries=0 --reporter=list
```

Exit 0. 26 passed (27.6s). Screenshots are 1440×900.

`npm run typecheck` exited 0 on this tree. `npx --no-install eslint` on the edited web files exited 0 with `--max-warnings=0`. `npx --no-install prettier --check` on those files exited 0.

## Backend pytest

Master push run `42986030371` on `dad086216f323f0caf1b39ec0eb4115515ec54eb` (build job `130407288706`) reported `6439 passed, 1 skipped`. This change does not modify the API. The pull request `build` job is the re-check for this head.

## Out of scope

Other navigation items keep their previous flags. `requiresEdit` and `requiresAdmin` still filter the same way. The existing list test still expects a reviewer to see Exports and Incoming Trust requests, an editor to miss the admin section, and an admin to see Alerts / Notifications without Account Security in that list. No other item was on `requiresEdit`. Tracker, backlog, and Jira snapshots are unchanged.
