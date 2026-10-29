# Keyboard and focus — TC-14-005

Checked in `apps/web/e2e/release/state-components.spec.ts` with a synthetic session and mocked responses. Dark theme. No customer data.

## Error (HTTP 500 on dashboard shortcuts)

The alert heading "Something went wrong" receives focus when the error appears. Tab moves to the "Try again" button. The button is a native `button`, so Enter and Space activate it. The word "Error" is visible text above the heading. The state does not depend on color alone.

The same pattern is used for offline ("Offline"), HTTP 403 ("This section is not available"), and HTTP 404 ("We could not find that"). Each has `role="alert"` and `data-failure` of `offline`, `forbidden`, or `not_found`.

A failed session uses the same control as a level-1 heading, then "Try again", then "Back to login".

## Empty

"No shortcuts yet" is a heading, not an alert. From the main region, Tab reaches the "Open documents" button. That action is shown only after a successful empty payload.

## Taking longer

The skeleton is `aria-busy` with the text "Loading dashboard". After 8 seconds the skeleton is replaced by a `role="status"` region. Focus moves to "This is taking longer than usual". Tab moves to "Try again". Activating it sends the request again. In the spec, the retried request returns the shortcut and the slow state goes away. The eyebrow "Still loading" is visible text.

## Partial success

"Some sections didn't load" is an alert heading and takes focus. "Try again: Security notices" is a button in that alert. Shortcuts that loaded stay outside the alert, so they are not announced as part of the error. The eyebrow "Incomplete" is visible text.

## Axe

`@axe-core/playwright` ran with tags `wcag2a`, `wcag2aa`, `wcag21a`, and `wcag21aa` on `#main-content` for the error, empty, and timeout states at 1440 CSS px. Each report has `violationCount: 0`. Screenshots for error, empty, timeout, and partial success are at 360, 768, and 1440 CSS px.
