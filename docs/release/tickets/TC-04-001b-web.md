# TC-04-001b-web — Use the workspace creation policy in the web app

## Behavior

Signed-in screens that can create a workspace read `GET /api/workspaces/creation-policy` before showing a form. The response used by the screen is the boolean `can_create_workspace`. A response with any other shape is treated as unavailable.

- While that read is in progress, the create form and the create action stay unmounted.
- When the boolean is false, the form and the create action stay hidden. Settings, onboarding, and checkout show the existing invitation notice, including the contact link when one is configured.
- When the boolean is true, settings shows the create form. Onboarding shows the workspace name form again. The submit button stays on "Creating…" until the request finishes. It does not switch to a past-tense label before that.
- When the read fails, or the body is not exactly that boolean, the form and the create action stay hidden. The screen says the check could not be completed and offers Try again.
- A submit that is refused still uses the existing invitation, maximum, and wait handling. Those responses do not repeat the response body.

Checkout keeps the invitation notice when creation is allowed and when it is not. The previous checkout combined account setup and billing with a workspace step, so that flow is not restored here.

The screen does not show counts, windows, or other fields from the read. Those values are not written into the page or the browser console.

## Acceptance criteria

- AC1: Workspace creation is hidden when `can_create_workspace` is false or the read is unavailable, including while the read is still pending.
- AC2: The create form is shown when `can_create_workspace` is true. Onboarding shows its name form. Checkout stays on the invitation notice.
- AC3: Cap and throttle values are not shown in copy, DOM attributes, or client logs.
- AC4: Submit-time 403, 409, and 429 handling still explains the invitation, the maximum, and the wait.
- AC5: Existing release gates stay in place and pass, including the new policy spec.

## Tests

`apps/web/tests/unit/workspace-creation-policy.test.ts` covers the parser, the reader, and the shared hook.

`apps/web/e2e/release/workspace-creation-policy.spec.ts` mocks an allowed read, a refused read, and a failed read. It checks settings, onboarding, checkout, and the command palette. Axe (WCAG 2.1 AA) runs on the allowed, refused, and failed states. Screenshots are at 360, 768, and 1440. Evidence is `artifacts/acceptance/TC-04-001b-web/`.

`web-release-e2e` runs that spec with the other release specs. The checker adds `--require-spec e2e/release/workspace-creation-policy.spec.ts --min-tests 14` and `--axe-dir ../../artifacts/acceptance/TC-04-001b-web`. Existing gates stay in place. The job keeps `permissions: contents: read` and `persist-credentials: false`.

## What this ticket does not change

The create request and its refusal responses stay as they are. Checkout does not regain the account and billing steps. Rollback is reverting this change.
