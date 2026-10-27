# TC-08-005 acceptance evidence

Synthetic data only. There were no LLM/model calls and no external services. Tests ran in a
container attached to an `--internal` Docker network (no egress) with `OPENAI_API_KEY` empty.
No credentials were used.

## Environment
- Implementation SHA: see the PR head commit (branch `tc/core/TC-08-005`). Baseline / origin/master: `c20f949161ac12a619b396d30904448ffd74d532`.
- DB: `pgvector/pgvector:pg16` (PostgreSQL 16.15, vector 0.8.7), test DB `trustcopilot_test`, migrated by conftest to alembic head `075`.
- App/test image: `apps/api/Dockerfile` target `base` (python:3.11-slim, deps from pyproject) **plus `sqlalchemy<2.1` (2.0.55)**. See the environment note below.
- pytest 9.1.1, pgvector-python 0.5.1, psycopg2-binary 2.9.13.

Environment note: pyproject leaves `sqlalchemy` unpinned. A fresh install resolves to SQLAlchemy
2.1.6, which maps `postgresql://` to psycopg v3, but only `psycopg2-binary` is installed. The
image as built therefore cannot connect to Postgres, and every DB test skips. This is
pre-existing and out of scope here. It was worked around in the test image only; nothing in the
repo was changed for it.

## Command (from `apps/api`)
```
python -m pytest -p no:cacheprovider tests/test_session_concurrency.py -v
```
(The ticket proposes `tests/release/test_session_concurrency.py`. Per Coordinator ruling Q3 the file is in `tests/`.)

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
