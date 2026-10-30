# TC-04-001b-web — Use the workspace creation policy in the web app

## Behavior

Signed-in screens that can create a workspace read `GET /api/workspaces/creation-policy` before showing a form. The response used by the screen is the boolean `can_create_workspace`. A response with any other shape is treated as unavailable.

- While that read is in progress, the create form and the create action stay unmounted.
- When the boolean is false, the form and the create action stay hidden. Settings and onboarding show the existing invitation notice, including the contact link when one is configured.
- When the boolean is true, settings shows the create form. Onboarding shows the workspace name form again. The submit button stays on "Creating…" until the request finishes. It does not switch to a past-tense label before that.
- When the read fails, or the body is not exactly that boolean, the form and the create action stay hidden. The screen says the check could not be completed and offers Try again.
- A submit that is refused still uses the existing invitation, maximum, and wait handling. Those responses do not repeat the response body.

Checkout is public and offers no creation or billing form. It renders the existing invitation notice and configured contact link without reading the authenticated creation-policy endpoint. Anonymous pricing visitors therefore retain the invitation and back navigation when that endpoint would return 401 or is unavailable. The previous checkout combined account setup and billing with a workspace step, so that flow is not restored here.

The screen does not show counts, windows, or other fields from the read. Those values are not written into the page or the browser console.

## Acceptance criteria

- AC1: Workspace creation is hidden when `can_create_workspace` is false or the read is unavailable, including while the read is still pending.
- AC2: The create form is shown when `can_create_workspace` is true. Onboarding shows its name form. Checkout stays on the invitation notice.
- AC3: Cap and throttle values are not shown in copy, DOM attributes, or client logs.
- AC4: Submit-time 403, 409, and 429 handling still explains the invitation, the maximum, and the wait.
- AC5: Existing release gates stay in place and pass, including the new policy spec.

## Tests

`apps/web/tests/unit/workspace-creation-policy.test.ts` covers the parser, the reader, and the shared hook.

`apps/web/tests/unit/checkout-invitation.test.ts` renders the real checkout and invitation components with anonymous 401 responses available. It checks email/HTTPS sales contacts, absent contact, focused invitation, back navigation, no forms and no API requests.

`apps/web/e2e/release/workspace-creation-policy.spec.ts` retains the authenticated allowed, refused, failed, pending, retry and malformed-policy checks for settings/onboarding and the command palette. Its three public checkout cases use anonymous 401 or unavailable-policy fixtures and require zero policy reads, no creation forms, preserved invitation/contact and pricing navigation. The spec still has 14 cases. Axe (WCAG 2.1 AA) and screenshots cover authenticated policy states plus public invitation/contact states at 360, 768, and 1440. Evidence is `artifacts/acceptance/TC-04-001b-web/`.

`web-release-e2e` runs that spec with the other release specs. The checker adds `--require-spec e2e/release/workspace-creation-policy.spec.ts --min-tests 14` and `--axe-dir ../../artifacts/acceptance/TC-04-001b-web`. Existing gates stay in place. The job keeps `permissions: contents: read` and `persist-credentials: false`.

## What this ticket does not change

The create request and its refusal responses stay as they are. Checkout does not regain the account and billing steps. Rollback is reverting this change.

## Anonymous checkout correction — 2026-10-30

[PR #77](https://github.com/Johnathan-u/trust-copilot/pull/77), assigned by
[#85 comment6511823848](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6511823848).
The correction follows pure master merge `cf1189990ff0ca57f5477258db7cbb3b261de46a`
in a separate commit. The creation-policy API requires authentication; using it
to gate a public invitation replaced the invitation/contact with a retry-only
failure for anonymous users. The correction changes checkout's component
selection only. Shared auth/UI, settings, onboarding, backend and owner gates
remain unchanged. Local checks and remaining exact-head qualification are in
the acceptance README.
