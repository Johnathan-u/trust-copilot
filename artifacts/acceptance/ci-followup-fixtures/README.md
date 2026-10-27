# ci-followup-fixtures: fresh-DB evidence

Every run used a brand-new, empty, per-run Postgres DB named `tc_ci_<label>_<epoch>_test` in a fresh container started from
`pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`.
Each container was bound to 127.0.0.1 only and removed after the run. The DB password was generated per run and is never printed.
Other settings: `TC_REQUIRE_DB=1`, `OPENAI_API_KEY` unset, `SESSION_SECRET=test-secret`, `-p no:cacheprovider`, Python 3.11.

`pytest-randomly` is not installed, so `-p no:randomly` is a no-op (the default order is alphabetical by file). Reverse order uses
`tc_reverse_order.py` (in this directory; loaded via `PYTHONPATH=<dir> -p tc_reverse_order`), which reverses the collected items.

| Log | Scope | Result |
|---|---|---|
| `full-reverse-before.txt` | full suite, reverse, base `3ee20da` with no fix | 4 failed, 1283 passed, 3 skipped |
| `alone.txt` | `test_vendor_requests_api.py::test_create_with_questionnaire_id` alone | 1 passed |
| `file-no-randomly.txt` | `test_vendor_requests_api.py`, `-p no:randomly` | 20 passed |
| `file-reverse.txt` | `test_vendor_requests_api.py`, reverse | 20 passed |
| `siblings-forward.txt` / `siblings-reverse.txt` | vendor_requests + export_pack + security_remediation | 38 / 38 passed |
| `full-forward.txt` | full suite, `-p no:randomly` | 1287 passed, 3 skipped |
| `full-reverse.txt` | full suite, reverse | 1 failed, 1286 passed, 3 skipped |

Before the fix, these 4 tests failed in reverse order: `test_create_with_questionnaire_id`, `TestExportPackService.test_cover_page`,
`test_switch_workspace_preserves_session_id` and `test_generate_answers_passes_document_ids_to_retrieval`.
The first three are fixed on this branch. The remaining failure (`tests/test_questionnaire_answer_evidence.py:200`, which picks the first
questionnaire and document in the DB) has been order-dependent since before this branch. It needs a fixture redesign, so it is listed for E11 rather than fixed here.
