# TC-08-005 acceptance evidence

Synthetic data only. There were no LLM/model calls and no external services. Tests ran in a
container attached to an `--internal` Docker network (no egress) with `OPENAI_API_KEY` empty.
No credentials were used.

## Environment
- Original local runs recorded no commit SHA (branch `tc/core/TC-08-005`). Baseline / origin/master then: `c20f949161ac12a619b396d30904448ffd74d532`. Exact SHAs are in the CI sections below.
- DB: `pgvector/pgvector:pg16` (PostgreSQL 16.15, vector 0.8.7), test DB `trustcopilot_test`, migrated by conftest to alembic head `075`.
- App/test image: `apps/api/Dockerfile` target `base` (python:3.11-slim, deps from pyproject) **plus `sqlalchemy<2.1` (2.0.55)**. See the environment note below.
- pytest 9.1.1, pgvector-python 0.5.1, psycopg2-binary 2.9.13.

Environment note: pyproject leaves `sqlalchemy` unpinned. A fresh install resolves to SQLAlchemy
2.1.6, which maps `postgresql://` to psycopg v3, but only `psycopg2-binary` is installed. The
image as built therefore cannot connect to Postgres, and every DB test skips. This is
pre-existing and out of scope here. It was worked around in the test image only; nothing in the
repo was changed for it.

## Command (from `apps/api`)

Original local runs, before the file moved. Those runs did not record a commit SHA.

```
python -m pytest -p no:cacheprovider tests/test_session_concurrency.py -v
```

The test now lives at `tests/release/test_session_concurrency.py`. The ticket command is:

```
python -m pytest tests/release/test_session_concurrency.py -q
```

## Results
| Run | Exit | Totals |
|---|---|---|
| New test, branch | 0 | 9 passed, 0 skipped (also repeated 5× more: 9 passed each) |
| New test vs **baseline** `retrieval.py` (regression proof) | 1 | 6 failed, 3 passed. The failures include `InvalidRequestError: This session is provisioning a new connection; concurrent operations are not permitted` |
| Related suites (9 files: answer evidence/generation, gaps, evidence search, questionnaire evidence/mapping) | 0 | 69 passed |
| Full `tests/` baseline c20f949 | 1 | 2 failed, 1284 passed, 3 skipped, 2 errors |
| Full `tests/` branch | 1 | 2 failed, 1285 passed, 2 skipped, 2 errors |

The full-suite failures and errors are identical on baseline and branch, so they are
pre-existing:
- `test_answer_pipeline.py::test_partial_completion_progress`
- `test_p1_multi_tenant_hardening.py::...::test_generate_answers_blocked_at_quota` (503 vs 429)
- 2 collection errors in ad-hoc scripts `test_alerts_api.py` and `test_coverage_api.py`, which
  call `localhost:8000` at import time.

The files in this directory are the raw summaries.

## Prior CI record (path before the move)

Master push run [42327658604](https://github.com/Johnathan-u/trust-copilot/actions/runs/42327658604)
at `55d7deece26ebcf52634f95a4554a31121c3a849` (`55d7dee`). Build job `128266592362`
and `web-release-e2e` job `128266592596` both succeeded. The file was still
`tests/test_session_concurrency.py`. This is the earlier qualifying run, not a run of
the moved path.

- Command: from `apps/api`, `pytest -rs`, with `SESSION_SECRET=test-secret`,
  `TC_REQUIRE_DB=1`, `TC_REQUIRE_WEB_TOOLCHAIN=1` and `TC_REQUIRE_API_QUALITY=1`.
  That step collects every test under `tests/`, including this file.
- Environment: GitHub-hosted `ubuntu-26.04` image `20261101.186.1`; Python 3.11.18;
  pytest 9.1.1; SQLAlchemy 2.0.55; psycopg2-binary 2.9.13; pgvector 0.5.1.
  PostgreSQL image `pgvector/pgvector:pg16` (16.15, vector 0.8.7), digest
  `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`.
  Database `tc_ci_42327658604_1_test` on `127.0.0.1:5432`.
- Exit status: 0.
- Totals: `tests/test_session_concurrency.py ......... [ 96%]` (9 passed, 0 skipped).
  Full suite: 6318 passed, 1 skipped, 51 warnings. The skip is
  `tests/test_trust_scoring_blind.py:33` (external data) and is unrelated.

## Moved file

`apps/api/tests/release/test_session_concurrency.py` is the path under test from this
branch on. The run of that path, at this pull request's CI head, is added in a
follow-up commit. That commit cannot name its own SHA.
