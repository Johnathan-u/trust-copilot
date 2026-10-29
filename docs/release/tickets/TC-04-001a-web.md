# TC-04-001a-web — Clear UI when workspace creation is unavailable

## Behavior

`/onboarding` and `/checkout` do not offer workspace creation and do not ask the server to create one. There is no endpoint that tells the client whether creation is available, so both screens explain that up front.

The notice says access is set up by invitation and asks the person to ask their workspace administrator for an invite. Sign out and Back stay available. Onboarding returns home from Back. Checkout returns to pricing. Focus moves to the notice. The wording carries the meaning; the surface color is not the only cue.

A contact link is an owner decision and is still open. Until that contact is configured, the link stays hidden. When it is configured as an email address, it opens a mail message with the subject “Workspace access”. When it is configured as an https URL, the link uses that address. Any other value is ignored.

Settings still has a create action for someone who already administers a workspace. If that request is refused:

- A refusal that creation is not available uses the same invitation explanation and disables the create action. The contact link appears only when a contact is configured.
- A conflict says the person has reached the maximum number of workspaces they can administer. The create action stays available.
- Too many attempts says to try again later. When the response includes a wait, the notice shows that wait in words such as "2 minutes", and the create action stays disabled until the wait has passed.
- Any other failure keeps the message that screen already showed.

## Tests

`apps/web/e2e/release/workspace-create-denied.spec.ts` checks that `/onboarding` and `/checkout` render the invitation notice and do not send `POST /api/workspaces`. It also checks the three refusal responses, and one ordinary failure, on the settings create action. Axe (WCAG 2.1 AA) runs on each invitation and refusal state. Evidence is `artifacts/acceptance/TC-04-001a-web/`.

`web-release-e2e` runs that spec with the other release specs. The checker adds `--require-spec e2e/release/workspace-create-denied.spec.ts --min-tests 8` and `--axe-dir ../../artifacts/acceptance/TC-04-001a-web`. Existing gates stay in place. The job keeps `permissions: contents: read` and `persist-credentials: false`.

## What this ticket does not change

The server response for creating a workspace stays as it is. These screens do not gain a way to ask ahead of time whether creation is available. Restoring a creation form on `/onboarding` or `/checkout` needs that endpoint first, so the form is shown only when creation is available. Rollback is reverting this change.
