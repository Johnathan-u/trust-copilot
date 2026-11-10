# TC-11-001 acceptance evidence

## Current run (rollback runbook and release-doc repair)

The behaviour is already on master (PR #16, `1a0e614`). This repair does not change it. The sections below are the original local record. They say `down_revision 075`, `alembic downgrade 075`, and `tests/test_provider_adapter.py`. Those are not the current parent, the current rollback, or the current test path.

* Parent, from `apps/api/alembic/versions/076_tc11001_model_outcome_codes.py`: `down_revision = "tc21001_framework_catalog_rights"`.
* On current master, `alembic downgrade tc21001_framework_catalog_rights` reverts 27 revisions (this one and 26 descendants). The head is `tc17003_security_claims`. `alembic downgrade 075` reverts 28, those 27 plus `tc21001_framework_catalog_rights`. What that destroys, and the safe rollback, are in `docs/release/tickets/TC-11-001.md`. Leave `answers.outcome_code` and `jobs.error_code` in place. `jobs.error_code` is shared with TC-10-002 and must not be dropped while that is live. A forward migration is the alternative when a column itself has to go.
* Current test path: `apps/api/tests/release/test_provider_adapter.py`.
* Round trip on a fresh database: `tests/release/test_provider_adapter.py::test_migration_downgrade_and_upgrade_roundtrip`. It fails if this revision's downgrade or upgrade is broken. Its CI log line is added from the GitHub Actions run of the commit that introduces the test, and that note names the SHA.
* The shared suite already crosses this revision: `tests/release/test_domain_compliance_frameworks.py::test_migration_upgrade_downgrade_upgrade_again` (`alembic downgrade 075`, then `alembic upgrade head`). Build job `130016659560` of run [42869507410](https://github.com/Johnathan-u/trust-copilot/actions/runs/42869507410) (push of `4d68f479ad03bb2684b1c9c94e68fa3460ec8d88`) logs `tests/release/test_domain_compliance_frameworks.py ...........           [ 42%]` (11 dots, no skip). Collection in that job lists this test 11th in the file. Alembic files are unchanged from that SHA through `4a2403ddd7f0e10854ae4370e48138cf673569c1`.

Command, from `apps/api`:

```
python -m pytest tests/release/test_provider_adapter.py -q
```

`result.json` records that command. CI run ids are filled from the run of an earlier commit on this branch, and the file says which SHA they belong to. This record does not accept the ticket.

## Original local record (stale)

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
- DB: `pgvector/pgvector:pg16`; conftest migrates to alembic head (`075` on that baseline,
  `tc11001_model_outcome_codes` on that branch). The DB was downgraded to `075` before the baseline run and after the branch run. That `075` target is this original record only. On current master the parent of `tc11001_model_outcome_codes` is `tc21001_framework_catalog_rights`, and downgrading there reverts 27 later revisions. See the current section.

## Commands (from `apps/api`)
```
python -m pytest -p no:cacheprovider tests/test_provider_adapter.py -v
python -m pytest -p no:cacheprovider tests -q -rf -p no:randomly --continue-on-collection-errors
alembic current; alembic downgrade 075; alembic upgrade head; alembic downgrade 075
PYTHONPATH=. python probe.py        # baseline_vs_branch_probe.txt, --network none
```
These are the commands that produced the original logs. `alembic downgrade 075` was a one-step
downgrade only while this revision's parent was `075`. It is not the current rollback.
The file now lives at `apps/api/tests/release/test_provider_adapter.py`. The original path above
is the path these logs used, before the move into `tests/release/`.

## Results
| Run | Exit | Totals |
|---|---|---|
| New tests, branch (`new_tests_branch.txt`) | 0 | 38 passed |
| Full `tests/` baseline f72def3 (`full_base_summary.txt`) | 1 | 2 failed, 1285 passed, 2 skipped, 2 errors |
| Full `tests/` branch (`full_branch_summary.txt`) | 1 | 2 failed, 1323 passed, 2 skipped, 2 errors |
| Migration 076 down/up/down, original commit (superseded by the review follow-up below) | 0 | 076 → 075 → 076 → 075 |

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
The original check in `migration_rollback.txt` ran `alembic downgrade 075` when that was the
parent. Do not use it on current master. The safe rollback leaves `answers.outcome_code` and
`jobs.error_code` in place and deploys a build that does not use them. `jobs.error_code` is
shared with TC-10-002 and must not be dropped while that is live. See
`docs/release/tickets/TC-11-001.md`.

## Review follow-up (Coordinator review of PR #16)
Run with the same image against an isolated Postgres (`tc-core-11001-pg` on the internal network
`tc-core-11001-net`), `OPENAI_API_KEY` empty, fakes only.
- **Item 2:** answer-cache hits now get `grounded_unverified`, never `grounded`.
- **Item 3:** the migration was renamed to `076_tc11001_model_outcome_codes.py`, revision id
  `tc11001_model_outcome_codes`. This follow-up recorded down_revision `075`. The file on current
  master revises `tc21001_framework_catalog_rights`.

| Run | Exit | Totals |
|---|---|---|
| `tests/test_provider_adapter.py` (`new_tests_branch.txt`) | 0 | 45 passed (38 before, plus 7 new; the migration test was renamed and tightened) |
| Related suites (`followup_related_tests.txt`) | 1 | 90 passed, 1 failed (`test_partial_completion_progress`, which also fails on master), 3 skipped (no fixture document on a fresh DB) |
| Full `tests/` (`full_followup_summary.txt`) | 1 | 1330 passed, 2 failed, 2 skipped, 2 errors. f72def3 on the same DB: 1284 passed, 2 failed, 3 skipped, 2 errors, with the same failures and errors |
| Migration round-trip (`migration_rollback.txt`, regenerated) | 0 | head → 075 → head → 075 → head; columns are checked after each step |
| Collision check (`migration_collision_check.txt`) | 0 | A simulated TC-25-005 `076` next to ours gives two heads, which merge cleanly |
