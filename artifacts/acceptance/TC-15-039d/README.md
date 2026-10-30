# TC-15-039d — immediately readable Approve revision

Local implementation and verification are complete. Independent review and all four required jobs on the final published head remain pending. The original TC-15-039 parent remains **PENDING**, with its 3 AC and 6 DoD dispositions unchanged. These 3 supplemental child points earn no original-parent completion credit.

## Scope and source

The assigned base is `cc9cdf803d3ddfc7db35d157a0886fffbfc4c7ea`. Coordinator authority is [issue 85 comment 6526881683](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6526881683). Implementer: `codex_session_review`; independent reviewer: `codex_role_grants`; root alone publishes and merges.

Only the Approve revision call site adds `style.transitionProperty = 'border-color, text-decoration-color, fill, stroke'`. Foreground and background changes, including this control's hover background, become immediate. Existing hover tokens, focus outline, disabled predicate, handler, permissions and all other controls remain intact. Shared Button, the landed ghost repair, globals, lockfile and workflow are unchanged.

The tested product blob is `91c0702f6add53c7ec20de1b5a8e16bf62d76ec2` and the final owning-spec blob is `f4464dae61cc94332f716d68e15f481c6ca06e75`. Removing the four added style lines reproduces the base page byte for byte. The entire original spec is a literal prefix of the new file. Its 63 expectation expressions comprise 62 outer matcher calls and one nested `expect.any(String)`; all remain byte-identical, as do the original 22 cases, three scans, scope/tags, diagnostic payload and attachment ordering. Six cases append 13 expectation expressions. See `source-proof.json` and `assertion-preservation.json`.

## Cause and regression oracle

The historical [PR149 push job](https://github.com/Johnathan-u/trust-copilot/actions/runs/41079072723/job/124143016499) reported one serious color-contrast node in the unchanged incoming Trust keyboard case at 768px. Its actual foreground/background are `#6b778c` on `#1a2436`, ratio **3.44** against the unchanged **4.5:1** threshold. `ci/` retains the full violation record and artifact provenance; this is historical input, not qualification of this child.

The new regression follows native keyboard behavior: focus Reply 21, Tab to review acknowledgment, Space to remove disabled, and Tab to Approve revision. A MutationObserver on that actual disabled removal flushes computed styles and pauses any browser-created color/background transitions at time zero. It does not inject colors, change eligibility or replace the button. This keeps the actual transient available for axe to inspect rather than relying on machine timing. The initial theme is settled before the observer is installed; the enable-state scan receives no delay or settled-state wait. Cleanup disconnects the observer and completes held animations even on failure.

Each case attaches full violation details, computed native state and a screenshot before its serious/critical assertion. The passing path also attaches hover state, checks the existing hover palette and 2px keyboard outline, unchecks acknowledgment with Space, verifies the native disabled state, and confirms no approve request was sent. Existing API fixtures qualify browser control paths; these tests do not claim live API, database or provider integration.

## Observed checks

| Check | Actual result |
| --- | --- |
| Initial untouched-page regression, dark/light × 360/768/1440 | Six expected failures at the serious-contrast assertion; one actual Approve node per case. Dark 3.44; light disabled palette `#64748b` on `#e2e8f0`, 3.86. |
| Final-spec unchanged-page control, dark/768 | Expected failure at the same contrast assertion, exact CI node and 3.44 palette. |
| Final-spec foreground-only control, light/768 | Expected failure: white text on the still-disabled `#e2e8f0` background, **1.23**. Foreground-only correction is rejected. |
| Final corrected owning suite | **28 passed**, zero skipped, unexpected or flaky; retries zero. All 22 original and six new cases pass. |
| Axe outputs | All three original and six new candidate scans have zero violations. |
| Existing Trust consumer/page unit suite | **25 passed** in one file. |
| Next typegen and TypeScript | Both exit 0. |
| Scoped ESLint / Prettier | Both exit 0; zero warnings. |
| Source preservation | Exact original spec prefix; all 63 expressions retained; only the selected page override changes product bytes. |
| Artifact gates | Actual unmodified pre-commit-hooks v4.6.0 EOF/trailing-whitespace entrypoints, all new text files; see `artifact-hooks.json`. |

The first six baseline failures and initial 28-pass suite preceded a lint-only change from two unused `.color` expressions to explicit `getPropertyValue('color')` calls. Assertions and observer behavior were unchanged. Both final-source negative controls and the final full 28-case suite ran afterward. `validation.json` records every phase, actual report statistics, commands, source hashes and raw-report provenance.

## Reproduction and toolchain

Existing locked tools were reused: Node 24.22.1, Next 16.4.3, Playwright 1.64.1, axe Playwright 4.14.0 and **Chromium 156.0.8078.4**. No dependency was installed or changed. The exact browser is `/tmp/tc-pr149-pinned-chrome/chrome-headless-shell-linux64/chrome-headless-shell`.

The isolated source snapshot is `/tmp/tc-15-039d-work/snapshot/apps/web`. Its product and spec bytes match this child. Next dev served only loopback port 13255, with `API_UPSTREAM=http://127.0.0.1:18099`, telemetry disabled and a separate `.next-approval-contrast` directory. Temporary Next-generated type includes are recorded in `source-proof.json`; no tracked configuration changed. This local run uses Next dev, with exact-head repository CI still required.

From that snapshot, the final full run was:

```sh
TC_APPROVAL_PHASE=final-owning-suite /opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/node node_modules/@playwright/test/cli.js test --config /tmp/tc-15-039d-work/playwright.config.cjs --project=chromium --retries=0
```

The retained `commands/local-playwright.config.cjs` pins the executable, owning spec, one worker, zero retries, the unchanged 30-second case timeout and isolated outputs. The controls use the same command with `--grep 'approval palette.*dark at 768px'` or `--grep 'approval palette.*light at 768px'` and temporary page-only source variants. Those variants never touched tracked source. Candidate bytes were restored exactly. Normal repository CI runs the same owning spec through its unchanged existing workflow/configuration.

Additional commands, from the same snapshot:

```sh
node node_modules/vitest/vitest.mjs run lib/trust-request-consumer.test.ts --maxWorkers=1
node node_modules/eslint/bin/eslint.js app/dashboard/trust-requests/page.tsx e2e/release/screen-trust-requests.spec.ts --max-warnings=0
node node_modules/prettier/bin/prettier.cjs --config /workspace/scratch/3faeebcaa421/trust-copilot-approval-contrast/.prettierrc --check app/dashboard/trust-requests/page.tsx e2e/release/screen-trust-requests.spec.ts
NEXT_DIST_DIR=.next-approval-contrast node node_modules/next/dist/bin/next typegen
node node_modules/typescript/bin/tsc --noEmit -p .
```

## Evidence and limits

- `candidate/`: closed **final-owning-suite** state, axe, hover JSON and screenshots at both themes and all three widths. These files do not come from the negative-control output directories.
- `controls/`: all six initial baseline state/violation records, two baseline visuals and both final-source negative controls.
- `original-scans/`: the three unchanged owning scans from the final green run.
- `commands/`, `validation.json`: concise transcripts and exact execution metadata. Complete local raw reports remain under `/tmp/tc-15-039d-work`; their hashes are retained.
- `evidence-manifest.json`: byte counts and SHA-256 for every retained evidence file except the manifest itself.

All six final screenshots were visually inspected: the enabled label and focus outline are visible at 360, 768 and 1440px in both themes. The sibling disabled Save control remains distinct. Committed JSON copies are normalized to one terminal LF without changing parsed values. Retained command transcripts strip trailing whitespace and surplus blank EOF lines; validation preserves raw transcript hashes. Full HTML/ZIP bundles and unrelated axe pass lists are deliberately not duplicated here. Fresh CI state/axe/visual attachments will be available in the existing uploaded Playwright HTML report without a workflow change.

Holding actual transitions establishes the failing state and distinguishes the two candidate behaviors; it does not estimate natural failure frequency. The full parent permissions/assignment, attachment/storage, live-provider and acceptance gaps remain open. Root must independently qualify build and web-release-e2e on both push and pull_request for the exact published head before merge.
