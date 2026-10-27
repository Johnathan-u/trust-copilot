# TC-10-003 acceptance evidence

- Implementation commit: `bae6cb8` (feature), merged with `origin/master` `6641e02` in `7d7bf9e`. The tests were run at `7d7bf9e` (code tree identical to the branch head; later commits only add docs and evidence).
- Environment: Python 3.11.18, SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0, pytest 9.1.1;
  PostgreSQL 16.15 with pgvector 0.8.7 (`pgvector/pgvector:pg16`) in a disposable local container on an internal
  network without egress. The test database was fresh (`*_test`) and `alembic upgrade head` was applied first, as in `.github/workflows/ci.yml`.
- Data: synthetic only. Storage is an in-memory fake, embeddings and retrieval are fakes, and the LLM is never invoked (patched to fail the test if
  it is called). `OPENAI_API_KEY` is empty, or a placeholder string in 2 tests. No outside service was contacted.
- Test location: `apps/api/tests/test_job_idempotency.py`. It is not under `tests/release/`, per Coordinator ruling Q3.

| Artifact | Command | Result |
|---|---|---|
| `test_job_idempotency.txt` | `TC_REQUIRE_DB=1 pytest -rs -v tests/test_job_idempotency.py` | 22 passed, exit 0 |
| `full_suite_branch.txt` | `alembic upgrade head && TC_REQUIRE_DB=1 SESSION_SECRET=test-secret pytest -rs` | 1309 passed, 3 skipped, exit 0 |
| `full_suite_master_6641e02.txt` | same command on `origin/master` 6641e02 | 1287 passed, 3 skipped, exit 0 |
| `migration_rollback.txt` | `alembic downgrade 075` → inspect → `alembic upgrade head` → inspect, plus offline `--sql` up and down | rollback and re-apply are clean |

The 3 skips are the same on master. They are local-only fixtures and are not required for this ticket.
Lint: `ruff==0.5.6 check .` passes and `ruff format` leaves the touched files unchanged.

## AC mapping

- **AC1 (crash before or after each effect does not duplicate anything):**
  - `test_parse_crash_after_commit_*`, `test_parse_crash_before_commit_*`, `test_parse_second_job_reconciles_*`
  - `test_index_rerun_after_commit_*`, `test_index_second_job_same_version_*`
  - `test_generate_rerun_is_idempotent_and_counts_usage_once`
  - `test_export_crash_after_upload_before_record_reuses_key`, `test_export_record_job_id_is_unique`
  - `test_enqueue_dedupes_only_queued_jobs`, `test_enqueue_race_returns_winner_via_unique_index`
  - `test_export_route_*` (Idempotency-Key)
- **AC2 (stale input cannot overwrite newer or approved work, and charge uncertainty is recorded):**
  - `test_parse_stale_input_is_superseded[storage_key|deleted]`, `test_index_stale_input_version_is_superseded`
  - `test_generate_never_overwrites_approved_or_newer_answers`, `test_upsert_guard_rechecks_answer_approved_mid_run`
  - `test_index_crash_during_provider_call_records_uncertain_charge`, `test_failure_path_marks_unsettled_provider_calls_uncertain`
  - `test_jobs_api_reports_charge_uncertain`
- **Migration rollback:** `test_migration_downgrade_and_upgrade_roundtrip` and `migration_rollback.txt`.
