# TC-04-006c implementation evidence

Base `bc423f11f74b23bd56a3d92e1f9b491c39c60258`; isolated branch
`codex/TC-04-006c-logout-ui`. Local results below apply to the committed source
containing this file; no real browser/PostgreSQL qualification is claimed locally.

The initial 17 DOM controls on the unchanged page returned **16 failures / 1 pass**:
all new-action cases failed at the missing button; the existing revoke-others case
passed. A shared-pending control was then added, for 18 final controls. Happy-dom
has no layout, so its trigger rectangle is supplied only for the shared dialog's
focus-restoration availability check. Chromium tests assert real focus geometry.

Self-review also reproduced a boolean-guard defect: a second same-tick callback
closed the shared dialog before the first request settled. The strengthened control
failed at the missing pending alertdialog; returning the same completion promise
keeps it busy until the original operation settles.

Two temporary runtime negative controls failed as intended and were restored:

- Removing the local synchronous guard: one selected double-confirm test failed
  because two POSTs were dispatched (17 other cases deselected).
- Removing strict acknowledgment validation: all seven selected malformed-success
  cases failed (11 other cases deselected).

`verification.txt` records the final commands, counts and environment limitations.
All existing CI bytes remain unchanged after removing the one new upload step.
Runtime edits are confined to `security/page.tsx`; all other additions are tests,
their dedicated configuration, docs/evidence, and the permitted artifact upload.

## Required real acceptance

Run from `apps/api`, with the repository's migrated local test PostgreSQL and locked
web toolchain/Chromium installed:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_logout_all_browser.py -q
```

The harness owns two users/two workspaces, all their login-created sessions, any
missing startup catalog tags it explicitly inserts, and its own service process
groups. Each viewport uses three independent real logins. A private filesystem
checkpoint coordinates before/after full-row database comparisons without adding
an API route or overriding auth/storage/business behavior. Cleanup is by explicit
owned IDs, followed by full baseline row-hash equality. The pre-existing Trust
browser module is not present on this API branch; its guarded subprocess pattern is
kept local here while reusing `_inbox_service` / `_inbox_wait_ready` directly.

The six axe JSON files contain the complete violations data, `width`, `state` and
integer `violationCount === violations.length`. They are written before zero-violation
assertions, so failed accessibility checks retain details. Page/dialog screenshots,
Playwright JSON/HTML reports, DB assertions and process/network evidence are uploaded
by the added `logout-all-acceptance` CI artifact step. The harness requires three
passed cases at 360/768/1440, six fresh axe files, screenshots and zero skipped/flaky/
unexpected results. HTTP/network/malformed response controls are explicitly mocked
unit evidence; the three browser positive cases use actual API/DB responses.

No generated screenshot, axe result or browser success report is checked in because
none was produced by an actual local browser run. Parent TC-04-006 remains open for
idle/activity policy and visible expiration warnings. Independent review, dependency
integration and all four exact-head CI gates are required before qualification.

## Independent-review report repair

The initial `15e8a6f` browser helper typed the password with `pressSequentially`.
The installed Playwright 1.64.1 renderer maps that to `Frame.type`, whose title and
parameter metadata include the supplied text even when tracing is off. `Frame.fill`
also includes its value. Sources inspected: `playwright/lib/index.js`'s
`onApiCallBegin`, and `playwright-core/lib/coreBundle.js` metadata entries/renderers.

The scoped replacement uses `locator.evaluate` to invoke the native password-input
value setter and dispatch an input event. Its credential is a separate serialized
argument, omitted by the installed `ElementHandle.evaluateExpression` report
metadata. The unchanged form button performs the real login and checks the real
API's response. No cookie is constructed and no successful auth response is mocked.

The new pytest unit regression extracts this actual helper with the installed
TypeScript parser, runs the DOM operation in happy-dom, and exercises the installed
Playwright metadata renderer, step recorder and HTML/JSON reporters. It verifies an
actual generated passing result and an intentional failure result, with full error
details retained. Neither report nor the HTML's decoded embedded ZIP members may
contain the synthetic marker. Changing the helper back to password typing fails
this regression. This controlled metadata/DOM fixture does not claim real Chromium
execution; the original three positive browser cases remain the real acceptance.

A final upload-directory scan withholds offending credential-bearing or unreadable
report files and fails acceptance. The regression injects plain JSON and compressed
HTML leaks to prove the failure is not silently accepted, and proves safe failure
diagnostics survive. Trace/video capture stays off. Reports/screenshots and all six
axe artifacts remain required; no assertion or output requirement was removed.

Repair verification: 30 pytest unit/safe-collection checks pass; typecheck, focused
ESLint, Prettier, Ruff and collection pass. AST comparison preserves all 43 original
browser expectations, the complete axe writer and 21 original real-browser/DB
assertions. Runtime page, web unit controls, browser configuration and ci.yml match
`15e8a6f` byte-for-byte. Real PostgreSQL/Chromium qualification remains pending.
