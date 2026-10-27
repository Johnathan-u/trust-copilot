# TC-11-001 acceptance evidence

All data is synthetic. No LLM/model or embedding calls were made: every provider is a fake
client, provider exceptions are built locally from real `openai` exception classes, and the
new tests block `socket.connect`/`connect_ex`/`create_connection`. pytest ran in a container on
an `--internal` Docker network (no egress) with `OPENAI_API_KEY` empty; the probe ran with
`--network none`. No credentials were read or used. The marker strings `SYNTH-PROVIDER-BODY-7f3a9c`
/ `SYNTH-SECRET` stand in for provider bodies and are asserted absent from every public surface.

## Environment
- Implementation SHA: the PR head commit (branch `tc/core/TC-11-001`). Baseline and origin/master
  are `f72def39245abf5cb46c7b3693f687114fa4b1b5`.
- Test image: `apps/api/Dockerfile` target `base` (python 3.11, `openai` 3.39.0 on `httpx2`) plus
  `sqlalchemy<2.1` (pre-existing psycopg2/SQLAlchemy 2.1 environment finding from TC-08-005,
  worked around in the image only).
- DB: `pgvector/pgvector:pg16`; conftest migrates to alembic head (`075` on baseline, `076` on
  branch). The DB was downgraded to `075` before the baseline run and after the branch run.

## Commands (from `apps/api`)
```
python -m pytest -p no:cacheprovider tests/test_provider_adapter.py -v
python -m pytest -p no:cacheprovider tests -q -rf -p no:randomly --continue-on-collection-errors
alembic current; alembic downgrade 075; alembic upgrade head; alembic downgrade 075
PYTHONPATH=. python probe.py        # baseline_vs_branch_probe.txt, --network none
```
The ticket proposes `tests/release/test_provider_adapter.py`. Under Coordinator ruling Q3 the file
lives in `tests/` because `tests/release/` is owned by TC-02-001.

## Results
| Run | Exit | Totals |
|---|---|---|
| New tests, branch (`new_tests_branch.txt`) | 0 | 38 passed |
| Full `tests/` baseline f72def3 (`full_base_summary.txt`) | 1 | 2 failed, 1285 passed, 2 skipped, 2 errors |
| Full `tests/` branch (`full_branch_summary.txt`) | 1 | 2 failed, 1323 passed, 2 skipped, 2 errors |
| Migration 076 down/up/down (`migration_rollback.txt`) | 0 | 076 → 075 → 076 → 075 |

Same failures/errors on baseline and branch (pre-existing on master):
- `test_answer_pipeline.py::test_partial_completion_progress` – needs a real `OPENAI_API_KEY`
  (now raises `ModelCallError`, a `ValueError` subclass, with the identical message).
- `test_p1_multi_tenant_hardening.py::TestAPIQuotaEnforcement::test_generate_answers_blocked_at_quota`
  – expects 429, gets 503 because the key check runs before the quota check.
- Collection errors in `test_alerts_api.py` and `test_coverage_api.py` (ad-hoc scripts that call
  `localhost:8000` on import).
Known flaky (not seen this run): `test_questionnaire_answer_evidence.py::test_generate_answers_passes_document_ids_to_retrieval`.

## Baseline vs branch behaviour (`baseline_vs_branch_probe.txt`)
On baseline, refusal, malformed output, missing model (404) and rejected credentials (401) all
collapse into `insufficient_evidence` / "Insufficient evidence." identical to "no evidence", and
the ALERT log line contains the raw provider error text. On the branch each case has a distinct
typed outcome, 404/401 stop the run with a safe `ModelCallError`, and the log line carries only
`code`, `provider_status` and `exception_type`.

## AC mapping
- AC1 (distinct outcomes): `test_ac1_six_outcomes_distinct`, classification/envelope/assess tests,
  pipeline tests (fatal stops after one call; missing key and embedding failure make zero calls).
- AC2 (one public schema, no provider payloads): ApiError tests for the 503 route, `GET /api/jobs`
  `error_detail` after a real `_process_one_job` failure, `outcome_payload`, request-ID
  propagation; secret marker absent from bodies, job error, logs.

## Rollback
Revert the commit and run `alembic downgrade 075` (drops nullable `answers.outcome_code` and
`jobs.error_code`; no data migration). Verified in `migration_rollback.txt`.
