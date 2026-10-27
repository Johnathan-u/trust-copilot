# TC-02-001 acceptance evidence — Isolate test collection from live services

All data synthetic. No production host, paid API or external account was contacted.
Credentials: the session secret that was hardcoded at baseline is referred to as
"[REDACTED hardcoded session secret]" (sha256 prefix `9368da37…d6c8`); it appears in no file here.

## Commit / baseline

| Item | Value |
|---|---|
| Baseline SHA (master) | `c20f949161ac12a619b396d30904448ffd74d532` |
| Branch | `tc/platform/TC-02-001` (head SHA recorded in the PR / commit containing this file) |
| Working dir for all commands | `apps/api` |

## Environment

| Item | Value |
|---|---|
| OS | Linux 6.12 (agent sandbox) |
| Python | 3.13.5 (venv). CI uses 3.11 per ci.yml; Dockerfile uses 3.11-slim |
| Key packages | fastapi 0.162.0, starlette 1.10.0, SQLAlchemy 2.0.55 (pinned `<2.1` locally because 2.1 defaults to psycopg3, not installed — lock file is TC-02-002), psycopg2-binary 2.9.13, alembic 1.20.1, pytest 9.1.1, httpx 0.28.1, openai 3.39.0 |
| Postgres | throwaway container `pgvector/pgvector:pg16` bound to `127.0.0.1:55432` (branch) and `127.0.0.1:55433` (baseline worktree); DB `trustcopilot_test`, synthetic `postgres/postgres` creds |
| DB selection | `TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/trustcopilot_test` (new override; validated local + `_test` suffix) |
| Provider env | no OPENAI/Anthropic/Stripe/etc. keys present; conftest scrubs them anyway |
| Node | v20.19.2 (used only to evaluate `playwright.config.ts` guard) |

## Results

| # | Command | Exit | Totals | File |
|---|---|---|---|---|
| 1 | `python -m pytest tests/release/test_safe_collection.py -q` (branch) | 0 | **26 passed**, 0 skipped | `release-test.txt` |
| 2 | same release test copied onto baseline tree (regression proof) | 1 | 16 failed, 10 passed | `release-test-against-baseline.txt` |
| 3 | `python -m pytest --collect-only -q` (baseline) | 2 | 1288 collected, **2 errors** (`tests/test_alerts_api.py`, `tests/test_coverage_api.py` made HTTP requests to `localhost:8000` at import) | `baseline-collect-only.txt`, `baseline-collect-socket-trace.log` (4 socket connects during collection) |
| 4 | `python -m pytest --collect-only -q` (branch) | 0 | 1314 collected, 0 errors, 0 socket connects (asserted by release test #1 with a sitecustomize socket tracer + hostile canary env) | `branch-collect-only.txt` |
| 5 | `python -m pytest -q` full suite (baseline worktree; conftest pointed at 55433, `.env` loading disabled, two import-time HTTP modules ignored) | 1 | 2 failed, 1284 passed, 3 skipped | `baseline-full-suite.txt` |
| 6 | `python -m pytest -q` full suite (branch) | 0 | **1313 passed, 2 skipped, 0 failed** | `branch-full-suite.txt` |
| 7 | `python -m pytest -m unit -q` with `TC_TEST_DATABASE_URL` pointed at closed port `127.0.0.1:1` | 0 | 239 passed, 1 skipped, 1075 deselected | `unit-no-db.txt` |

Marker selection (branch, collect-only): `-m unit` 239, `-m integration` 1075, `-m provider` 0, `-m external_data` 0 collected
(the external_data module skips at module level with reason
"external_data: blind test pack not checked in; set TC_TRUST_SCORING_BLIND_PACK to run" — see skipped list).

Skips in run #6 (both explained, none required by the AC):
1. `tests/test_trust_scoring_blind.py` — `external_data`, blind pack not in repo.
2. `tests/test_control_timeline.py::TestControlTimelineService::test_timeline_includes_review_if_present` — pre-existing data-conditional skip ("No reviewed workspace controls"), also skipped on baseline.

Network guard report in run #6: `tests/test_alerting_verification.py::test_openai_failure_logs_ALERT_OPENAI_FAILURE`
attempted `dns:api.openai.com` 3× at run time; the guard blocked it (on baseline this test made real outbound calls to OpenAI
with an invalid key). The test asserts the failure alert path, so it still passes.

Baseline failures fixed (#5 → #6): `test_answer_pipeline.py::test_partial_completion_progress` and
`test_p1_multi_tenant_hardening.py::TestAPIQuotaEnforcement::test_generate_answers_blocked_at_quota` only passed when a
real `OPENAI_API_KEY` was loaded from the repo-root `.env`. They now use the `synthetic_openai_key` fixture
(fake key, OpenAI client already mocked, network guard on).

## After merging ci-repair (which includes ci-mechanical), the CI-green head

Merge `c69ae5f` brings tc/platform/ci-repair 3ee20da into this branch, resolved as in
`TC-02-001-after-ci-repair.diff`:

- `scripts/manual_live/*` take this ticket's side.
- `tests/conftest.py` takes this ticket's hunks and keeps ci-repair's `TC_REQUIRE_DB` fail-loud session check.
- The two test modules take this ticket's side.
- The safe ruff, whitespace and prettier recipe then runs.

The merged `ci.yml` keeps the pinned pgvector service and `TC_REQUIRE_DB: "1"`, and adds the
"Safe test collection (TC-02-001)" step.

All checks below ran at SHA `c69ae5f`, and the logs are in `after-ci-repair/`. They used a local mirror
of the CI `build` job, including the safe-collection step: fresh Python 3.11 venv, digest-pinned
`pgvector/pgvector:pg16` in a fresh container, a per-run `*_test` DB with generated credentials and
`OPENAI_API_KEY` unset.

| Check | Exit | Totals | File |
|---|---|---|---|
| `pre-commit run --all-files` | 0 | all hooks Passed, 0 files modified | `after-ci-repair/precommit.txt` |
| `ruff check .` (0.5.6), `alembic upgrade head` | 0 / 0 | All checks passed; migrations OK (pgvector 0.8.7) | `after-ci-repair/ci-local.txt` |
| Safe test collection: `python -m pytest --collect-only -q` | 0 | **1315 collected**, no live calls | `after-ci-repair/ci-local.txt` |
| release test `python -m pytest tests/release/test_safe_collection.py -q`, plain and with `TC_REQUIRE_DB=1` | 0 / 0 | **26 passed** / **26 passed** | `after-ci-repair/ci-local.txt` |
| full suite `python -m pytest -rs -q`, `TC_REQUIRE_DB=1` | 0 | **1313 passed, 3 skipped** (1 `external_data` blind pack, 2 seed-data skips; none about the DB) | `after-ci-repair/ci-local.txt` |
| `npm run build` (apps/web) | 0 | Compiled successfully | `after-ci-repair/ci-local.txt` |
