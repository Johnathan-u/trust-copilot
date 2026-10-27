# TC-03-003 acceptance evidence — Separate readiness, liveness and worker health

All data synthetic; no production host, paid API or external account contacted. No credentials appear in these files.

| Item | Value |
|---|---|
| Baseline | `c20f949161ac12a619b396d30904448ffd74d532` |
| Implementation commit | `214560f` (branch `tc/platform/TC-03-003`) |
| Merged head (master `f72def3` merged in, merge commit) | `0aff48c40cbbc7595fed893147d2d01b8a99aefa` |
| Python / key packages | 3.13.5 venv; SQLAlchemy 2.0.55, psycopg2-binary, FastAPI (CI uses 3.11) |
| Database | throwaway `pgvector/pgvector:pg16` container on `127.0.0.1:55432` (branch) / `:55433` (baseline worktree), DB `trustcopilot_test`, synthetic creds; `tests/conftest.py` temporarily redirected by a wrapper and reverted (never committed) |
| Provider env | `OPENAI_API_KEY` unset |

## Results
| # | Command (from `apps/api`) | SHA | Exit | Totals | File |
|---|---|---|---|---|---|
| 1 | `python -m pytest tests/release/test_health_probes.py -q` | 0aff48c | 0 | **24 passed** | `release-test-merged-head.txt` |
| 2 | same | working tree on c20f949 (pre-commit) | 0 | 24 passed | `release-test.txt` |
| 3 | release test copied onto baseline c20f949 (regression proof) | c20f949 | 1 | 23 failed, 1 passed | `release-test-against-baseline.txt` |
| 4 | existing health tests `tests/test_api_contracts.py tests/test_alerting_verification.py` (1 deselected: real OpenAI call on master) | 0aff48c | 0 | 13 passed, 1 deselected | `existing-health-tests-merged-head.txt` (also `existing-health-tests.txt`) |
| 5 | full suite `python -m pytest -q -rs` (2 import-time-HTTP modules ignored, 1 real-OpenAI test deselected — both pre-existing master issues fixed in ci-repair/TC-02-001) | pre-commit tree | 1 | 3 failed (pre-existing, `OPENAI_API_KEY`-dependent), 1307 passed, 2 skipped, 1 deselected | `branch-full-suite.txt` |

The one release test that passes on baseline (`test_liveness_never_touches_dependencies`) documents behaviour that already held and must be preserved.

## AC mapping
See `docs/release/tickets/TC-03-003.md` §Acceptance criteria → evidence. AC1: 5 tests; AC2: 19 tests.

## Not verified here
Real Docker `HEALTHCHECK` execution in a built image / compose stack (verified by static tests on the Dockerfile and compose files plus the probe CLI end-to-end against a temp heartbeat file). Reviewer sign-off (DoD) is outstanding.

## After merging ci-repair (which includes ci-mechanical), the CI-green head

Merge `02a07e8` (tc/platform/ci-repair 3ee20da into this branch) uses the resolution in
`TC-03-003-after-ci-repair.diff`: `app/main.py` and `app/worker.py` take this ticket's side, then
the safe ruff recipe runs. Follow-up `8f444d3` untracks an `apps/web/node_modules` symlink, a
local tool link, that the merge picked up by accident. Both logs below come from tested SHA `8f444d3`
and live in `after-ci-repair/`. They were run through a local mirror of the CI `build` job:
fresh Python 3.11 venv, digest-pinned `pgvector/pgvector:pg16` in a fresh container, a per-run `*_test`
DB with generated credentials, `TC_REQUIRE_DB=1` and `OPENAI_API_KEY` unset.

| # | Check | Exit | Totals | File |
|---|---|---|---|---|
| 7 | `pre-commit run --all-files` | 0 | all hooks Passed, 0 files modified | `after-ci-repair/precommit.txt` |
| 8 | `ruff check .` (0.5.6) and `alembic upgrade head` | 0 / 0 | All checks passed; migrations OK (pgvector 0.8.7) | `after-ci-repair/ci-local.txt` |
| 9 | release test `python -m pytest tests/release/test_health_probes.py -q` | 0 | **24 passed** | `after-ci-repair/ci-local.txt` |
| 10 | full suite `python -m pytest -rs -q`, with nothing ignored or deselected | 0 | **1311 passed, 3 skipped** (seed-data skips only, none about the DB) | `after-ci-repair/ci-local.txt` |
| 11 | `npm run build` (apps/web) | 0 | Compiled successfully | `after-ci-repair/ci-local.txt` |

Rows 7–11 supersede the pre-existing failures noted in #4–#5: ci-repair fixed the import-time HTTP calls, the real-OpenAI calls and the shared-DB issues.
