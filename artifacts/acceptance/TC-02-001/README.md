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
