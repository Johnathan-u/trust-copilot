# TC-06-002i export-worker authorization evidence

Base: `dea5f5afe87dfa73a0321a0f0311847ed233432f`. Claim: #85 comment
6533395283. Three provisional child points; zero original-parent completion credit.

The worker now validates positive JSON integer references and requires the current
persisted job workspace, its loaded workspace and payload workspace to agree. It
loads the current active questionnaire before replay or effects. Any existing
job-linked export record must match that exact questionnaire and workspace; a
mismatch fails before rendering or attempting a replacement artifact. All invalid
or unavailable references use the same terminal `bad_input` message, without IDs
or foreign metadata. The rest of `run_export` and every other worker function are
unchanged; file hashes and the AST comparison are in `verification.json`.

## Executed results

Commands below ran from `apps/api` using `/tmp/tc-backend-venv/bin/python`.
The retained logs contain the actual command output, including existing datetime
deprecation warnings. `red-sqlite.log` has trailing whitespace normalized and the
JUnit XML has a terminal newline added, as documented below; neither is presented
as byte-exact raw output. No real model, provider or object-storage calls were made.

| Command after the Python executable | Result | Evidence |
|---|---|---|
| `-m pytest tests/release/test_authorization_export_worker.py -k sqlite -q` against unchanged production | 63 expected failures, 3 positive controls passed | `red-sqlite.log` |
| `../../artifacts/acceptance/TC-06-002i/negative_controls.py baseline_added_cases` | All 4 subsequently added stale-file/deleted-job cases fail against the exact original `run_export`, loaded only in memory | `red-added-cases.log` |
| `-m pytest tests/release/test_authorization_export_worker.py -k sqlite -q` with the fix | 70 passed; 70 PostgreSQL counterparts deselected | `green-sqlite.log` |
| `-m pytest tests/test_export_literal_text.py tests/test_export_golden.py tests/release/test_job_leases.py tests/release/test_job_cancellation.py -m unit -q -ra --junitxml=../../artifacts/acceptance/TC-06-002i/related-export-and-lifecycle-unit.xml` | 44 passed, 34 deselected | `related-export-and-lifecycle-unit.log`, `.xml` |
| `-m pytest tests/release/test_job_retries.py -k 'classifier_table or typed_errors or safe_error_message or retry_after_parsing or backoff or attempt_ceiling or write_guard' -q` | 40 passed, 30 deselected | `related-job-errors.log` |
| `-m pytest tests/release/test_safe_collection.py -q` | 29 passed | `safe-collection.log` |
| `-m pytest tests/release/test_authorization_export_worker.py tests/release/test_job_idempotency.py tests/release/test_job_retries.py tests/release/test_job_cancellation.py tests/release/test_job_leases.py --collect-only -q` | 298 collected, including all 140 new variants | `collection.log` |
| `-m ruff check app/worker.py tests/release/test_authorization_export_worker.py` | Passed | `verification.json` |
| `-m ruff format --check app/worker.py tests/release/test_authorization_export_worker.py` | Both files formatted | `verification.json` |

Seven isolated negative controls removed one guard at a time: job/payload
agreement, current persisted job lookup, active-parent filter, exact replay parent,
current replay columns, strict reference types, and current questionnaire file.
Each invocation produced the intended assertion failure; the wrapper required
pytest exit 1 and verified the production file hash stayed unchanged. See
`negative-*.log` and the reproducible `negative_controls.py`. No tracked source
was changed for these controls.

## Evidence formatting repair

PR #163 build run 124333213804 rejected evidence formatting: import ordering and
line length in `negative_controls.py`, trailing whitespace in `red-sqlite.log`,
and the missing terminal newline in `related-export-and-lifecycle-unit.xml`.
The repair is assigned in issue #85 comment 6534749154. It changes only this
child's acceptance artifacts; production, release tests, hooks and CI are unchanged.

The helper's formatting and import order are corrected, with the existing scrubbed
environment installed before importing the worker. The log is normalized only by
removing trailing whitespace; the XML differs only by its final newline. Original
SHA-256 values, Git blob/path references and the original published commit are
retained in `verification.json` under `evidence_normalization`, alongside hashes
of the normalized copies. The original bytes remain recoverable from Git history.
No test result or diagnostic content is removed, and historical test runs are not
relabeled as fresh execution.

The earlier full base-to-head whitespace check failed solely on the raw log; its
result remains recorded as historical evidence. `evidence_ci_repair` records the
fresh complete affected-file hook run, helper verification and whitespace checks.

## What the tests establish

Both database variants use actual models and constraints. SQLite enables foreign
keys and creates the unchanged model tables/indexes; PostgreSQL requires the
existing migrated fixture. Rows are inserted, moved, archived or physically
deleted with ordinary ORM/SQL operations. No trigger, constraint, schema, auth,
source lookup, renderer, quota or side-effect implementation is replaced.

The only replacements are `StorageClient.download`, `upload` and `delete`, the
external object-storage boundary. Valid XLSX and DOCX bytes are rendered by real
production code and inspected for the own answer and absence of foreign answers.
Own replay preserves the artifact and counts quota once. A storage failure keeps
the existing rollback behavior. Job lifecycle fields remain unchanged by direct
handler execution, apart from result/automatic update timestamp.

Denied dispatch must issue only SELECTs, leave no pending ORM changes, preserve
every column of all ten observed tables, and make no storage call. Tests preserve
old ORM identities while updating current database rows to exercise current-state
authorization. Teardown deletes only fixture-owned primary keys and compares all
rows with the pre-test baseline. The existing network guard asserts no added
blocked egress attempts.

## Remaining qualification gates

The required full-project command was attempted with
`TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trustcopilot_test /tmp/tc-backend-venv/bin/python -m pytest`.
It exited **3 before tests**, because local PostgreSQL refused the connection.
`full-suite-strict-postgres.log` records this infrastructure blocker. No local
PostgreSQL execution or full-suite pass is claimed; no database was installed.

The 70 real PostgreSQL variants and existing idempotency, lease, retry and
cancellation integration suites remain mandatory in CI. New focused fixtures use
persisted running jobs with null lease owners, matching the existing export
idempotency fixture; they do not qualify the concurrent PostgreSQL claim/lease
loop. Independent review and `build` plus `web-release-e2e` on both push and
pull_request at the exact final head remain required before merge. This bounded
child does not accept the complete TC-06-002 parent.
