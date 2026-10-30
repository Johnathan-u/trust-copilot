# TC-15-025a acceptance evidence

Base: `8f0cc07872057007d635e7bee17687f5fadc696b`.
Branch: `codex/TC-15-025a-refresh-recovery`.
The tested change is this commit's `ui-23.spec.ts` diff. This record does
not claim a completed browser run or a repaired master.

## Failed master evidence

- Run: https://github.com/Johnathan-u/trust-copilot/actions/runs/41003220218
- Web job: https://github.com/Johnathan-u/trust-copilot/actions/runs/41003220218/job/123892180051
- Playwright artifact ID: `12954536591`.
- Outcome: 239 passed, one failed; the sole failure was
  `permission revocation clears a confirmed private gap title and action state`
  at the Refresh gaps click, formerly `ui-23.spec.ts:1325`.
- The inspected error context/screenshot showed the section error already
  focused, with private title, dialog and Refresh gaps absent. The recorded
  navigation began at `04:35:23.107`; Confirm was clicked at `04:35:23.952`,
  acknowledgment focus was checked at `04:35:24.024–24.049`, and Refresh gaps
  began at `04:35:24.050`. The 60-second poll was not due.
- These artifacts were inspected before the runtime reset. Their former local
  extraction under `/tmp/tc-master-gap-failure` did not survive recovery; this
  record does not represent those files as currently available local artifacts.

## Source and controlled orders

`EvidenceGapList.onConfirmed` applies the acknowledged row, focuses the notice,
closes the dialog and calls `result.retry()`. `useSnapshot` clears private data
and action state on 401/403/404. The original notice-focus wait did not establish
that the ensuing GET had completed. Thus the mock's new denial state could affect
the automatic GET before the manual click.

The browser repair holds that GET explicitly. For the existing manual case, a
distinct reason returned only by the automatic response must render before
denial is enabled and Refresh gaps is clicked. For the new automatic case, the
held GET receives 403. The two cases share all original acknowledgment-focus,
redaction, dialog-clearance and retry assertions, and assert that the denied
read occurs exactly once and the Refresh control is absent afterward.

A temporary diagnostic at `/tmp/tc-gap-order-recovery/repro.test.ts` mounts the
actual production gap list and action dialog in happy-dom; only fetch is
controlled. In both orders it first observes the focused acknowledgment while
the automatic GET is pending and captures the connected Refresh element. The
automatic-denial path proves that element becomes disconnected. The manual path
first releases and observes a distinct successful snapshot, then invokes denied
manual refresh. Both verify private-state clearing and successful retry without
stale notice/dialog. Result: 2 passed. The diagnostic and its temporary config
are not committed and do not substitute for the 30-case browser suite.

## Verification and outstanding qualification

Commands and actual results are in `verification.txt`. Local unit tests, type
checking, focused lint, formatting and browser case collection passed. The
Chromium launch probe failed because the executable is absent; no browser tests
were executed locally. No runtime, dependency or CI configuration changed.

Independent review and exact-head build plus web-release-e2e checks on both push
and pull_request remain required, followed by master CI verification. Existing
browser accessibility, viewport, permission, revocation, focus and retry
assertions are retained; no passing screenshot or axe result is claimed for this
new head until CI supplies it.
