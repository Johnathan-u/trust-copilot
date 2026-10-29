# Compliance gaps verification

Status: gap actions added after #83 merged; exact-head action browser checks and
full ticket acceptance remain pending. AC6 is still TC-21-007b.

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
