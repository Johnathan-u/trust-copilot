# TC-04-001a-web — Clear UI when workspace creation is unavailable

## Behavior

`/onboarding` and `/checkout` do not offer workspace creation and do not ask the server to create one. There is no endpoint that tells the client whether creation is available, so both screens explain that up front.

The notice says access is set up by invitation, and that the person should ask an administrator of their organization for an invite or contact sales. Contact sales is a mailto link because the app has no contact page. Sign out and Back stay available. Onboarding returns home from Back. Checkout returns to pricing. Focus moves to the notice. The wording carries the meaning; the surface color is not the only cue.

Settings still has a create action for someone who already administers a workspace. If that request is refused:

- A refusal that creation is not available uses the same invitation explanation, disables the create action, and links to contact sales.
- A conflict says the person has reached the maximum number of workspaces they can administer. The create action stays available.
- Too many attempts says to try again later. When the response includes a wait, the notice shows that wait in words such as "2 minutes", and the create action stays disabled until the wait has passed.
- Any other failure keeps the message that screen already showed.

## Tests

`apps/web/e2e/release/workspace-create-denied.spec.ts` checks that `/onboarding` and `/checkout` render the invitation notice and do not send `POST /api/workspaces`. It also checks the three refusal responses, and one ordinary failure, on the settings create action. Axe (WCAG 2.1 AA) runs on each invitation and refusal state. Evidence is `artifacts/acceptance/TC-04-001a-web/`.

`web-release-e2e` runs that spec with the other release specs. The checker adds `--require-spec e2e/release/workspace-create-denied.spec.ts --min-tests 6` and `--axe-dir ../../artifacts/acceptance/TC-04-001a-web`. Existing gates stay in place. The job keeps `permissions: contents: read` and `persist-credentials: false`.

## What this ticket does not change

The server response for creating a workspace stays as it is. These screens do not gain a way to ask ahead of time whether creation is available. Restoring a creation form on `/onboarding` or `/checkout` needs that endpoint first, so the form is shown only when creation is available. Rollback is reverting this change.
