# TC-04-006d local acceptance evidence

Base commit: `dea5f5afe87dfa73a0321a0f0311847ed233432f`.
Exact production/test blobs: [source-blobs.json](source-blobs.json).
Claim: [#85/6533395283](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6533395283).
Review repair: [#85/6534340084](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6534340084).
This is a bounded 3-point child; TC-04-006 idle/activity acceptance remains open.
No CI result, merge, deployment or parent completion is claimed here.

## Implemented contract

`GET /auth/me` returns the same effective absolute deadline already computed by
`enforce_session_record`, plus server time (Unix seconds). Normal, onboarding and
MFA-enrol principals retain their existing restrictions. Tests compare complete
persisted rows, SQL reads, signed cookie identity and absence of Set-Cookie.

The dashboard warns in the final five minutes. Its minute display uses server
remaining lifetime and monotonic elapsed time, conservatively deducting request
latency. It never offers extension. Expiry revalidation uses response receipt as
the latest possible server observation, avoiding a premature read that could
leave an expired session stranded. During that small gap it displays a check,
not additional lifetime. Server 401 preserves the existing login redirect.

Auth refresh runs at the deadline, visibility return, explicit retry and workspace
switch. Superseded responses cannot overwrite a newer denial; unmount aborts
requests and removes timers/listeners. A failed/malformed timing check suppresses
the countdown. There is no periodic auth poll, idle policy or automatic renewal.
Remote policy/revocation is observed on the next server request, not continuously.

After an acknowledged workspace switch, the previous user, workspace and permissions
are withheld until `/auth/me` confirms a valid principal for the selected workspace.
Failed or superseded confirmation returns `false`; retries and racing refreshes must
still confirm that target before restoring access. Ordinary background refreshes keep
the existing offline behavior for an already confirmed workspace.

## Reproduction and observed results

Commands are relative to `apps/api` unless otherwise noted. Python is
`/tmp/tc-backend-venv/bin/python` (3.12.14). Real stored-auth SQLite fixtures keep
foreign keys enabled; corresponding PostgreSQL cases remain in the same matrix.

- Before API implementation:
  `python -m pytest tests/release/test_session_expiry_warning.py -k sqlite -q --tb=short`
  — **12 failed**, each missing `server_time`; 12 PG cases deselected.
  After implementation the same command: **12 passed**.
- Before context implementation (from `apps/web`):
  `./node_modules/.bin/vitest run tests/unit/session-expiry.test.ts`
  — **13 failed, 2 passed**. Initial banner stub:
  `./node_modules/.bin/vitest run tests/unit/session-expiry-warning.test.ts`
  — **3 failed, 1 passed**. Latency regression before the receipt-bound fix:
  context suite **3 failed, 13 passed**, including a null deadline after a delayed
  valid response. Rejected-switch regression before its fix: **1 failed, 18 passed**.
  Final focused suites: **23 passed**.
- `python -m pytest tests/release/test_session_expiry_warning.py tests/release/test_remember_policy.py tests/release/test_principal_contract.py -k sqlite -q --tb=short`
  — **101 passed**, 101 PG cases deselected. Existing SQLAlchemy datetime
  deprecation warnings remain.
- `python -m pytest tests/release/test_safe_collection.py -q`
  — **29 passed**.
- `python -m pytest tests/release/test_session_expiry_warning.py tests/release/test_session_expiry_browser.py --collect-only -q`
  — **25 collected**: 12 SQLite, 12 PostgreSQL and one real-browser orchestration.
- `TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trust_copilot_session_warning_test TC_REQUIRE_DB=1 python -m pytest tests/release/test_session_expiry_warning.py tests/release/test_session_expiry_browser.py -q`
  — **exit 3**, local PostgreSQL connection refused. No infrastructure installed,
  schema weakened or skip counted as successful qualification.
- `apps/web`: `npm run quality` and `NEXT_TELEMETRY_DISABLED=1 npm run build`.
  Typecheck, lint, format and **444 unit tests** passed; the production build
  passed. Final results are recorded in [checks.json](checks.json). Dependencies match the
  committed lockfile. A local copy of the existing locked node_modules replaced
  an initial symlink that Turbopack correctly rejected outside its workspace root.
  No dependency, config or lockfile change is part of this candidate.
- Ruff check/format and `git diff --check`: passed for all changed Python/source files.

## Independent-review repair

The reviewer reproduced a stale-workspace state after a successful switch POST and
failed `/auth/me`: the old workspace remained visible and switching returned `true`.
The repair started at `50b81d311cb19445cd748770d8ec0286d72713bd` and changes only
AuthContext, its focused unit tests and this child evidence; coordinator-owned CI
wiring is preserved.

Before the repair, `./node_modules/.bin/vitest run tests/unit/session-expiry.test.ts`
(from `apps/web`) produced **11 failed, 19 passed**. The new failures cover pending
confirmation, network failure, HTTP 401/403/503, invalid JSON, null/missing principal,
a mismatched workspace, a late pre-switch read and a superseding visibility refresh.
After the repair, the context and banner suites produce **34 passed**. Recovery via
explicit retry, ordinary offline refresh, rejected-switch handling and all existing
session timing cases remain covered. Fresh full frontend validation for this repair
is recorded separately under `review_repair` in [checks.json](checks.json). Browser
control artifacts below predate this repair; real API/PostgreSQL CI remains required.

## Browser evidence and remaining gates

The original implementation’s local Chromium control ran its production build with mocked
transport, using `python /tmp/tc-session-warning-local-browser/run.py` from
`apps/web`. Its exact runner, assertions, four axe reports and PNGs are in
[local-ui-control](local-ui-control/). It verified the five-minute appearance,
360/768/1440 wrapping without horizontal overflow, failed-check retry, keyboard
activation and deadline-to-login behavior; four scoped axe reports have zero
violations. Mobile warning and desktop retry screenshots were visually inspected.
The local test used no real credentials or external requests. It does **not**
qualify real API/PostgreSQL browser behavior.

Mandatory CI must run `test_session_expiry_browser.py` with a migrated PostgreSQL
DB and locked browser install. That harness owns real login users, persisted
sessions, exact-owned policy/revocation changes and cleanup; no HTTP auth response
is replaced. It launches two browser cases through
`playwright.session-expiry.config.ts` / `e2e/integration/session-expiry.acceptance.ts`:
ordinary cookie/current policy/absolute expiry, and remembered cookie/failed
check/retry/revocation. Visibility-return DOM events are dispatched in Chromium;
hidden-document scheduling is separately covered by context unit tests.

Required outputs: `apps/web/test-results/session-expiry/report.json` with **2
passed, 0 skipped/flaky/unexpected**; `axe-warning-{360,768,1440}.json` plus
`axe-unavailable-1440.json` (**4 zero-violation reports**) and companion PNGs;
`assertions.json`, `network.jsonl`, `processes.json`; HTML report under
`apps/web/playwright-report/session-expiry`. The fixture scans report payloads for
its private synthetic password before upload and verifies complete-row equality
after all reads/denials. Startup storage failures are isolated and recorded;
post-readiness provider/storage traffic fails the gate.

The coordinator owns CI workflow wiring, publication and independent review.
PostgreSQL execution, the two real API/browser cases, independent review and
exact-head push/pull-request CI remain required before integration.

Artifact formatting normalization adds the missing final newline to the five
`local-ui-control/*.json` reports. Their JSON values and all runtime/test source
blob identities remain unchanged; this formatting step does not rerun or upgrade
the recorded browser qualification.
