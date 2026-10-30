# TC-14-008b — Ghost-button contrast during theme changes

This is the separate three-point supplemental product repair claimed in
[#85/6524819383](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6524819383).
Original TC-14-008 acceptance remains **PENDING**; this child earns no original
parent points. Implementation: `codex_session_review`. Assigned independent
reviewer: `codex_role_grants`. The coordinator owns publication and merge.

## Proven defect and bounded correction

The retained [push web failure](https://github.com/Johnathan-u/trust-copilot/actions/runs/41066077500/job/124097709130)
on UI PR #149 reported two ghost export labels at `#707788` on `#ffffff`, 4.48:1
against the unchanged 4.5:1 requirement. `observed-ci/` retains that complete raw
axe result, originally artifact 12982124194. These product/style/spec/lock files
were identical on that head and green base `ac7f6ab990ae031a4d705d59afd7f22d045cccf2`.

The real browser creates a 150ms text-color transition from `#e8eefb` to
`#0f172a`; the transparent ghost buttons expose a panel that becomes white
immediately. Pausing that actual transition at 33.3ms reproduces the exact CI
selectors/color/ratio. Finishing the same animation yields `#0f172a` and 17.85:1
on white. A naturally timed passing rerun does not establish a repair.

The only product edit replaces `transition-colors` for the ghost variant with
`transition-[background-color,border-color,text-decoration-color,fill,stroke]`.
Only foreground `color` is excluded. Other variants retain the original list;
all remaining component bytes, dimensions, props, state, labels, actions,
duration/easing, disabled/loading and focus behavior are unchanged.

## Regression and negative controls

The owning spec appends one case at each of 360/768/1440px. Each changes the real
app theme in both directions, records immediate computed colors, holds any
browser-created foreground transition at 33.3ms, and calls the unchanged axe
helper. The helper still retains raw details and attaches before both original
zero-violation assertions. Actual pointer hover must create a background-color
transition; border-color must remain transitionable. Keyboard Tab must focus
Export XLSX with a visible outline. Six screenshots capture both themes.

| Run | Actual result |
| --- | --- |
| New regression with baseline Button | 3 expected failures: two nodes at 4.48:1 at every width |
| New regression with correction | 3 passed, both directions and hover/focus checks |
| Complete owning spec | 14 passed: all 11 original cases plus 3 additions |
| Original scan matrix | Six reports, zero violations |
| Added transition scan matrix | Six reports, zero violations |
| Exact original component restored only in temporary app | Expected 360px contrast failure |
| Ghost `transition-none` mutant only in temporary app | Contrast passes; missing hover transition fails |
| Exact candidate restored after controls | 360px case passes |
| Existing web unit suite | 403 tests in 42 files passed |
| Type generation/typecheck, scoped ESLint/Prettier | Passed |

All browser runs used zero retries and had zero skips/flaky cases. The two
negative controls changed only an isolated temporary app. The Git worktree
remained the candidate and its source bytes were restored in the temporary app
before the final positive check. `baseline/` and `negative-original/` retain
complete raw failing nodes/checks. The transition-none error is retained in
`commands/negative-hover.txt` and the execution summary.

## Source and execution proof

`assertion-preservation.json` verifies all 58 original expectation expressions
are identical, and the entire original spec/helper is an unchanged prefix plus
its original closing delimiter. The existing six-scan loop, WCAG tags,
thresholds, summary fields and raw-diagnostic attachment order are intact.
There are 9 added expectation expressions (67 total), exercised by three cases.

`verification.json` records source blob IDs, base, exact commands, environment,
per-test results, durations, zero-retry outcomes, raw-report hashes, controls,
known limitations and remaining gates. `green/` contains all 12 passing axe
reports; `colors/` contains the actual immediate and sampled browser colors;
`screenshots/` contains six synthetic dark/light captures. Command outputs are
in `commands/`; display-only trailing spaces/blank EOF lines are trimmed, and
`verification.json` pins each original raw log hash. `evidence-sha256.json` hashes the retained files.

The local app was an exact source snapshot on 127.0.0.1:13251, using Next 16.4.3
with Turbopack, existing copied locked dependencies, Playwright 1.64.1 and pinned
Chromium 156.0.8078.4. No dependency installation or version change occurred.
The source fixture uses real React/CSS/browser/axe and its existing synthetic
API route responses. This is not real-provider or PostgreSQL qualification.

The local browser command, run from the isolated `apps/web`, was:

```sh
TC_GHOST_PHASE=full-green node node_modules/@playwright/test/cli.js test   --config=/tmp/tc-14-008b-work/playwright.config.cjs   --project=chromium --retries=0
```

The copied local config fixes the existing browser executable, loopback port,
one worker, zero retries and separate report directories. It is retained only
as execution evidence. Repository configuration and workflows are unchanged.
Raw local reports remain under `/tmp/tc-14-008b-work/reports/`; the summary hashes
pin their exact contents without duplicating embedded screenshot bytes.

The initial isolated formatting check lacked the repository-root `.prettierrc`.
The final check explicitly uses that unchanged repository config and passes;
no source was reformatted to satisfy the temporary default. Logs retain the
existing color-environment and Vite future-config notices. ESLint has no warnings.

## Limits and remaining gates

All six images were inspected for this contrast repair. The existing review-page
`min-width:1120px` layout still clips narrow views; this child does not establish
full parent responsive acceptance. The two original AC and six original DoD
records remain unverified, and original scope/points are unchanged.

Independent review, `build` and `web-release-e2e` on both push and pull_request
for the exact final published head, coordinator merge and current-master CI are
still required. No local result substitutes for those gates. The PR #149 push
failure remains historical provenance and a blocker until its separate branch
is integrated and freshly qualified after this repair lands.
