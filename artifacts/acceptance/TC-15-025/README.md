# Compliance gaps verification

Status: AC6 source disclosure follow-up implemented against TC-21-007b and the
TC-21-007c question-source pair contract. Full ticket acceptance still requires
the dependency merge, independent review and exact-head browser checks. Historical
increment evidence below remains labelled with its own tested heads.

Environment: Linux x86_64, Node 24.22.1 / npm 11.9.0; locked `npm ci --ignore-scripts`.
All API data used by tests is synthetic. No database writes or provider calls.

The page implementation has passed local typecheck, lint and 27 unit-test files
(175 tests). An earlier production build passed before the final read-denial
regression and accessible report attachments. Exact final-head commands and their
logs are recorded after the implementation commit below.

Browser command: `npx playwright test e2e/release/ui-23.spec.ts`.
Local Chromium is unavailable (downloads return truncated archives); no local
browser, screenshots, keyboard or axe pass is claimed. CI includes this spec in its
explicit list. The existing Playwright HTML report retains attached screenshots
and axe JSON at 360/768/1440 when those tests run.

AC6 awaits recommendation source identifiers (see #85 comment 6503980646).
Decide/resolve are now implemented against merged #83, under ruling 6505384313.
The earlier read-only head `f16ca2c32feaa997d78c8ba085497d9d01153c47` passed
all four checks in runs 40925705452 and 40925716055 (54 browser tests, 11 ui-23);
those results do not qualify the new action code. Full backend contract integration
is not qualified by browser fixtures.

## Exact local checkpoint

Tested commit `592a8450faca4c569a728016bfaf9a33394d0aa1`, tree
`26488d27b7b910fab0348f7148320f3bc705aa1b`, after a pure merge of master
`a2458c9e2ae3c7b5f4cad7f293211afbb19e4687`.

| Command (apps/web)  | Exit | Result                                |
| ------------------- | ---- | ------------------------------------- |
| `npm run typecheck` | 0    | Type generation and TypeScript passed |
| `npm run lint`      | 0    | Zero errors/warnings                  |
| `npm run test:unit` | 0    | 27 files, 175 tests passed            |
| `npm run build`     | 0    | Production build succeeded            |

Logs are normalized for line endings and trailing whitespace only. No browser
result is included in these local totals. Independent review and exact-head CI
remain pending.

## Independent review corrections

The control denominator now remains visible when there are zero questionnaire
questions. KPI ratios are labelled retained answer records per question (which
can exceed 100%), and recommendation counts no longer imply distinct questions.
Hidden charts explicitly disable the Recharts accessibility layer; their equivalent
tables provide keyboard-accessible data. Browser regressions cover these cases.
After these changes, typecheck, lint, 175 unit tests and production build all
passed on the working tree captured by the following review-fix commit. Exact-head
CI and browser evidence remain required; the initial checkpoint logs above have
not been overwritten or presented as a later run.

## Action increment checkpoint

Master `8060788` was merged without rebase in a separate pure merge; the only
conflict was the CI candidate list, preserving both controls and ui-23 specs.
The action unit suite first failed because the implementation module did not
exist, then passed after implementation. Local typecheck, lint and all 184 unit
tests passed on the implementation working tree. Exact committed-tree logs and
production build results will be appended after the code checkpoint.

New browser cases cover decisions, 403/404/409, concurrent refresh, qualifying
evidence rejection, body-specific idempotency keys, lost responses, malformed
acknowledgments, notification partial failure, evidence search/paging and workspace
switches. Action dialogs attach axe JSON and screenshots at 360/768/1440 widths.
No local browser pass is claimed; all four exact-head CI checks remain required.

## Exact action implementation verification

Tested remote commit `a6b8558687e3ca60051cc835abdf77b5e1908962`, tree
`4a0bd4e363815df8da7180d97b3bb0baecc83af2`. The remote merge commit
`35f44ae07783744b967771202aa4e85107566e95` has parents `f16ca2c` and
`8060788`; its tree matches the local pure merge. The implementation tree also
matches the independent review checkpoint `c849b963`.

| Command (apps/web)                                     | Exit | Result                                |
| ------------------------------------------------------ | ---- | ------------------------------------- |
| `npm run typecheck`                                    | 0    | Type generation and TypeScript passed |
| `npm run lint`                                         | 0    | Zero errors/warnings                  |
| `npm run test:unit`                                    | 0    | 29 files, 184 tests passed            |
| `npm run build`                                        | 0    | Production build succeeded            |
| `npx playwright test e2e/release/ui-23.spec.ts --list` | 0    | 22 cases discovered; discovery only   |

`actions-*.log` records these commands against the exact commit. Logs are
normalized for carriage returns and trailing whitespace only. Independent review
verified the fix that clears private action notices/selections after a denied
refresh. The browser suite includes successful action followed by revoked access,
and checks that recovery does not restore stale confirmation state.

The first action browser run (40936474300, `a6b8558`) passed 85/86 release
cases, including all action acknowledgments, privacy and responsive axe cases.
The evidence-search recovery fixture failed because it returned failure only on
the first mount request; StrictMode may replace that request. The fixture now
keeps failure active until the test explicitly starts retry. No timeouts, product
logic or CI triggers were weakened. Final exact-head browser evidence is pending.

## AC6 provenance follow-up checkpoint

Branch `codex/TC-15-025-provenance`, base
`499f8af76c427dab5ef2f8ca7ffc2a257129e6ed`. Scope claim: #85 comment 6511660571.
Question mapping contract: Coordinator ruling #85 comment 6511727336 and
TC-21-007c / issue #113. The frontend consumes explicit
`question_sources: [{ question_id, questionnaire_id }]`, never a guessed parent
identifier or a questionnaire-list scan. This contract dependency must land
before full AC6 acceptance.

Environment: Linux x86_64, Node 24.22.1, npm 11.9.0, Next 16.4.3, Playwright
1.64.1. Installed dependencies were copied from the sibling `tc-demo-proof-race`
checkout after its `apps/web/package-lock.json` compared equal. No dependency or
configuration edits. All new API replies are synthetic; no live backend/provider
qualification, data mutations or permission changes are claimed.

Final local frontend commands (from `apps/web`):

| Command | Exit | Result |
| --- | --- | --- |
| `npm run lint` | 0 | Full frontend ESLint, no errors/warnings |
| `npm run test:unit` | 0 | 32 files, 213 tests passed; 12 new provenance regressions |
| `npm run format:check` | 0 | All matched frontend files formatted |
| `npm run build` | 0 | Production compilation, TypeScript and 39 static pages passed |
| `npx playwright test e2e/release/ui-23.spec.ts --list` | 0 | 29 tests discovered; discovery only |

The first targeted regression command,
`npm run test:unit -- tests/unit/compliance-gap-provenance.test.ts`, failed before
implementation because the new contract/component modules did not yet exist.
The final full suite above covers them. Unit checks include malformed/duplicate
IDs and pairs; missing legacy mappings; foreign evidence and mismatched question
responses; one scoped read per disclosed source; unavailable-source retry;
workspace/close cancellation; and timeout with ignored late response.

Browser attempt (from `apps/web`):

```sh
E2E_WEB_PORT=13413 E2E_SALES_WEB_PORT=13414 npx playwright test e2e/release/ui-23.spec.ts --project=chromium --workers=1 --retries=0 --max-failures=1
```

Next dev startup failed with `uv_interface_addresses` / `Unknown system error 1`.
The blocked command was interrupted, exit 130, before any test ran. A direct
browser prerequisite check was also run:

```sh
node -e 'require("playwright").chromium.launch({headless:true}).then(browser => browser.close()).catch(error => { console.error(error.message); process.exitCode=1 })'
```

It exited 1: the `chromium_headless_shell-1248` executable is absent. No download
was retried and no browser, screenshot, keyboard or axe pass is claimed. The
updated 360/768/1440 specs include expanded evidence/question disclosures and
retain their existing report attachments. Exact-head push and pull_request
`build` / `web-release-e2e` plus independent review remain required.

The following Git blob IDs pin the implementation and regression files checked
above, so the evidence can be compared with the eventual committed tree without
mistaking the historical heads for this follow-up:

| File (under `apps/web`) | Blob |
| --- | --- |
| `app/dashboard/compliance-gaps/page.tsx` | `5f75335058052cc279e7c7e3499d1851f58bdf6c` |
| `app/dashboard/compliance-gaps/recommendation-contract.ts` | `93f34cc415e5e93ca062d921a46f1c797d26df23` |
| `app/dashboard/compliance-gaps/recommendations.tsx` | `5d9d0abf14478595a290ee9379fc47b42db33332` |
| `tests/unit/compliance-gap-provenance.test.ts` | `b120ee6cee972319553ffcb584b6de5f7ea3f247` |
| `e2e/release/ui-23.spec.ts` | `14bbd5b42df7440da230395b8bc7fc63c74bcd2a` |

## Review correction — source labels without internal IDs

Assigned by [#85 comment6511936256](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6511936256).
Base implementation `1a66b62f943aa7bcd3a38b401ed8a765c6a2bb9b` and its authorship
are preserved; this narrow correction is a separate child commit.

Independent review found that disclosure/link labels exposed raw evidence,
control and question identifiers. They now use per-list positions, for example
`View evidence source 1`, `View control source 1` and `View question source 1`.
Actual IDs remain unchanged in React keys, scoped source requests and navigation
URLs. No data, permissions, request lifecycle or other product behavior changed.

The added real-component regression uses multiple arbitrary six-digit IDs in
reverse order. It checks that none appear in visible text before or after opening
sources, each ordinal targets its original item, selected evidence/question
reads retain their exact IDs and workspace, and the verified questionnaire link
retains its original parent ID. Before the label correction, this test failed on
visible `View evidence 871002` / `View control 841002` / `View question 831002` text.

The browser spec keeps all 29 cases. Existing interaction selectors now use the
human labels. The previous uppercase-only `Control 41` absence assertion is now
case-insensitive, and the recommendation case additionally checks that source
IDs are absent from visible text while retaining the exact control/questionnaire
hrefs and the two expected GET source requests.

Verification from `apps/web`, Node 24.22.1 / npm 11.9.0:

| Command | Result |
| --- | --- |
| `npx --no-install vitest run tests/unit/compliance-gap-provenance.test.ts -t 'labels sources by list position'` before correction | 1 failed on visible IDs, 12 unselected tests skipped |
| `npx --no-install vitest run tests/unit/compliance-gap-provenance.test.ts` after correction | 13 passed |
| `npm run test:unit` | 32 files, 214 passed |
| `npm run lint` | Passed, full frontend ESLint |
| `npm run format:check` | Passed, full frontend Prettier |
| `npm run typecheck` | Passed, route types and TypeScript |
| `npx --no-install playwright test e2e/release/ui-23.spec.ts --list` | 29 cases collected |
| `git diff --check` | Passed |

The direct Chromium launch prerequisite check still exits 1 because
`chromium_headless_shell-1248` is absent. Browser/axe/screenshot execution remains
unqualified locally; no repeat production build or browser pass is claimed for
this correction. Independent review and exact final-head CI are still required.
The final local commit/tree are returned to the coordinator for the live ledger.

## CI disclosure and workspace-fixture repair

Local base: `fa12957ee2a69ad85763795ff6544ed08240baee`; exclusive repair claim:
#85 comment 6512213604. The fetched logs for push run `40981535069`, browser job
`123822510438`, show 103 passed and two failed release cases. The disclosure case
recorded two GETs each for evidence and questionnaire detail. The workspace case
still found one match for `Quarterly access review` after switching.

A new real-component StrictMode regression reproduced the same duplicate GET
sequence before the fix. The source effect now defers request start one microtask,
allowing cleanup of the discarded StrictMode setup before it sends a request.
The surviving disclosure still performs a fresh read; close/reopen is explicitly
verified to read again. Existing abort, timeout, retry, workspace checks and
internal-only source identifiers remain unchanged.

The workspace browser fixture returned the original recommendation title in its
coverage response for both workspaces. That title also matched the stale evidence
picker assertion. The fixture now returns a distinct recommendation for the
second workspace, and the test confirms both old and new coverage snapshots.
All existing absence assertions and all 29 browser cases remain intact. No API,
auth, shared UI, workflow, dependency, or other product surface changed.

Verification from `apps/web`, Node 24.22.1 / npm 11.9.0:

| Command | Result |
| --- | --- |
| `npx --no-install vitest run tests/unit/compliance-gap-provenance.test.ts -t 'StrictMode replays'` before fix | 1 failed: duplicate evidence and questionnaire GETs |
| `npx --no-install vitest run tests/unit/compliance-gap-provenance.test.ts` after fix | 14 passed |
| `npm run test:unit` | 32 files, 215 passed |
| `npm run typecheck` | passed |
| `npm run lint` | passed, full frontend |
| Prettier check of the three changed web files | passed |
| `npx --no-install playwright test e2e/release/ui-23.spec.ts --list` | 29 cases discovered |
| Direct Chromium launch prerequisite check | exit 1: chromium_headless_shell-1248 executable absent |
| `git diff --check` | passed |

Tested blobs: `recommendations.tsx` `0b5586fb51881b12b54a013ecd710e316a100663`;
`compliance-gap-provenance.test.ts` `77ceef92f65d9ee81e09b7403e8030544fb2fad5`;
`ui-23.spec.ts` `0e783da0735e364ff25a122f17f1031fe7b951da`.
Local browser, screenshot and axe execution remain unqualified. Independent
review and exact-final-head push/pull-request CI checks are still required.

## Destination fixture follow-up

At published head `4ebe70d28d1ebb894cc56c300f730ff10cafaa49`, push run
`40983390140` browser job `123828570500` passed 104 cases and failed one: the
source-link scenario reached the questionnaire URL, but its page crashed on the
generic `{}` response for questionnaire answer statistics. Independent review
traced the missing `status_breakdown` field to that test fixture. The fixture now
returns the real statistics response shape, including empty breakdown objects.
The click, URL and question-text assertions are unchanged, and all 29 UI-23
cases still collect. Scoped Prettier and whitespace checks pass. No product
navigation change or local browser pass is claimed; final-head CI is required.
