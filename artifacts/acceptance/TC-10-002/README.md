# TC-10-002 acceptance evidence

- Branch `tc/core/TC-10-002`, based on `origin/master` `d527863` (#28 TC-10-003 merged, on top of #31 `e1c0ca7` and
  #16 TC-11-001 `1a0e614`). It is not stacked: the two commits sit directly on master. The tests ran on the final code;
  only this directory and the ticket doc were edited after the runs.
- Environment: Python 3.11.18, SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0, pytest 9.1.1; PostgreSQL 16 with
  pgvector (`pgvector/pgvector:pg16`) in a disposable local container on an internal Docker network with no egress.
  Each run used a freshly created `*_test` database and applied `alembic upgrade head` first, as in `.github/workflows/ci.yml`.
- Data: synthetic only. Provider errors are fake exception classes, `ModelCallError`s built from the TC-11-001
  catalog, and fake HTTP responses. The OpenAI client, embeddings and storage are patched, and `OPENAI_API_KEY` is
  empty. No model call was made and no outside service was contacted.
- Test location: `apps/api/tests/test_job_retries.py`, next to the other job tests (unchanged decision; see the PR body).

| Artifact | Command | Result |
|---|---|---|
| `alembic_roundtrip.txt` | fresh DB: `alembic upgrade head` → `alembic heads` → `alembic downgrade tc10003_job_idempotency` → `alembic upgrade head` → `alembic heads`, inspecting `jobs` columns at each step | chain `075` → `tc21001` → `tc11001` → `tc10003` → `tc10002`; `alembic heads` = `tc10002_job_retries (head)` only; downgrade drops only `next_attempt_at`; re-upgrade clean |
| `migration_rollback.txt` | the same downgrade/upgrade with a synthetic retry-scheduled job row, plus offline `--sql` up and down | the row survives; TC-11-001's `error_code` and TC-10-003's `idempotency_key` stay |
| `targeted_tests.txt` | `TC_REQUIRE_DB=1 SESSION_SECRET=test-secret pytest -rs -v tests/test_job_retries.py tests/test_job_idempotency.py tests/release/test_health_probes.py tests/release/test_health_probes_isolation.py` | **126 passed** (68 + 33 + 24 + 1), exit 0 |
| `regression_before_fix.txt` | the 8 completed-job tests (`-k "completed or completion or stale_attempt"`) with the worker guard stashed | 6 failed, 2 passed: without the guard, a completed job's `error_code` is overwritten or the job is re-queued |
| `full_suite_branch.txt` | `pytest --collect-only -q` → `pytest tests/release/test_safe_collection.py -q` → `TC_REQUIRE_DB=1 SESSION_SECRET=test-secret pytest -rs` | 1639 collected; safe collection 25 passed, 1 skipped; **1636 passed, 4 skipped, 0 failed, exit 0** |
| `full_suite_master_d527863.txt` | same, on `origin/master` `d527863` | 1571 collected; safe collection 25 passed, 1 skipped; **1568 passed, 4 skipped, 0 failed, exit 0** |

Branch vs master: +68 tests (all in `test_job_retries.py`), 0 new skips, 0 failures. The 4 skips are the same on
both: `test_trust_scoring_blind` (external data), `test_safe_collection.py:517` (node is not installed in the test
image; the static check still runs), and two data-dependent skips (`test_control_timeline`, `test_feedback_capture`).
The known order-dependent `test_generate_answers_passes_document_ids_to_retrieval` (fix in #32) passed in both runs.

Rebuilt on master: TC-10-002's logic commit applied to `d527863` with no textual conflicts. The base fixes that the
old stacked branch carried in its local merge `50a1a82` (`FakeEmbed(on_failure=)`, the single-head migration
assertion) are already on master through #28, so they are not in this branch.

Lint: `ruff==0.5.6 check .` and `ruff format --check .` pass in `apps/api`; there are no `.py` files under `artifacts/`.

## AC mapping

- **AC1: 429s, timeouts and 5xx retry with bounded backoff and jitter; bad input, auth and config errors stop explicitly.**
  - Classification: `test_classifier_table` covers 429, 408/504, 5xx, connection, DB, botocore codes, openai/httpx names,
    4xx, 401/403/404, missing credentials, and unknown → terminal. Also `test_typed_errors_keep_their_code_and_value_error_compat`
    and `test_retry_after_parsing`.
  - TC-11-001 model failures: `test_model_failures_keep_tc11001_codes_and_catalog_retryability`. `model_rate_limited` is
    re-queued with the catalog message. `model_quota_exhausted`, `model_credentials_invalid` and `model_request_rejected`
    fail on the first attempt.
  - Bounded backoff and jitter: `test_backoff_is_bounded_exponential_with_jitter`, `test_backoff_honours_retry_after_but_clamps_to_cap`,
    `test_attempt_ceiling_and_env_config`, `test_hard_ceiling_bounds_attempts_even_if_max_attempts_is_large`,
    `test_inner_completion_retry_uses_jittered_bounded_backoff`.
  - Retry scheduling: `test_transient_failure_schedules_bounded_retry_and_is_not_claimable_early`,
    `test_claim_increments_attempt_and_clears_schedule`, `test_process_one_job_end_to_end_retry_then_success`,
    `test_retry_not_requeued_when_identical_job_already_queued`.
  - Explicit stop:
    - `test_terminal_errors_stop_on_first_attempt` covers bad_input, not_found, auth_failed, permission_denied and config_error.
    - `test_generate_auth_error_stops_explicitly`: a 401 becomes `model_credentials_invalid`, terminal, with no provider body.
    - `test_generate_missing_api_key_is_terminal_config_error`: a missing key becomes `model_credentials_missing`, terminal.
    - Also `test_index_no_embeddings_raises_classified_errors`, `test_embed_texts_records_last_error_for_classification`
      and `test_unreadable_pdf_is_terminal_and_marks_questionnaire_failed`.
  - Generation: `test_generate_transient_llm_errors_retry_only_failed_questions`,
    `test_generate_bad_request_question_stays_visible_placeholder`, `test_write_guard_does_not_protect_llm_error_placeholders`.
- **Completed jobs keep the `error_code` a handler set (TC-02-BUG-015 will set `evidence_gaps_failed`).**
  - `test_success_keeps_error_code_the_handler_set_on_a_completed_job`
  - `test_retry_then_success_clears_only_the_stale_attempt_error`: a retry's stale `connection_error` is cleared on success.
  - `test_failure_handler_never_overwrites_a_committed_completion` (connection, unknown and auth errors): no re-queue, no
    `failed`, `error_code` unchanged.
  - `test_post_commit_exception_in_worker_loop_keeps_completed_error_code`: an exception raised after the completion
    commit leaves the job `completed` with its code.
- **AC2: retry exhaustion and the next attempt are visible and never labelled success.**
  - `test_retry_exhaustion_fails_visibly_never_completed`.
  - `test_jobs_api_exposes_retry_state` checks `error_code`, `retryable`, `next_attempt_at`, `retry_scheduled`,
    `retries_exhausted` and `max_attempts`, next to TC-11-001's `error_detail`.
  - `test_index_retry_keeps_document_pending_and_terminal_marks_failed`, `test_safe_error_message_never_contains_provider_body`.
- **Migration rollback:** `test_migration_downgrade_and_upgrade_roundtrip` (also asserts a single head and that
  `error_code` is not owned by this revision) and `migration_rollback.txt`.
