# TC-10-003f answer-write gaps

PR #204 was merged under the title TC-10-003a, but that ID already belonged to earlier TC-10-003 work: the 5xx no-cache and enqueue retry. After the merge, the PR and this folder were renamed TC-10-003f.

Parent: `a2b39c80` (squash merge of PR #202). The suite below ran on the working tree in this commit. Naming that commit here would change the SHA, so the branch head is the commit that contains this file.

Post-merge review: [PR #202 comment](https://github.com/Johnathan-u/trust-copilot/pull/202#issuecomment-6768438815). The merged head's CI is recorded in [`../TC-10-003/README.md`](../TC-10-003/README.md) (`review-191.md`, push run 42812533846, pull_request run 42812560479, master run 42817018001, merge `a2b39c80`).

## Environment

- Python 3.11.18, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0, ruff 0.5.6
- PostgreSQL 16.15 with pgvector 0.6.0 from Ubuntu packages, database `trustcopilot_test` on `127.0.0.1`. CI uses the pinned `pgvector/pgvector:pg16` image (pgvector 0.8.7). This run is not that image.
- Node 24.22.1. Frontend `npm run typecheck`, `npm run lint`, `npm run format:check`, and `npm run test:unit` (446 passed) completed, and `npm run build` completed.
- Synthetic rows only. Provider calls are patched. No model spend.

## Backend suite

```
cd apps/api
SESSION_SECRET=test-secret TC_REQUIRE_DB=1 TC_REQUIRE_WEB_TOOLCHAIN=1 TC_REQUIRE_API_QUALITY=1 \
  python -m pytest -rs --tb=line -q
```

Exit 0. **6394 passed, 1 skipped, 51 warnings** in 644.28s.

The skip is `tests/test_trust_scoring_blind.py:33`: external blind pack not checked in (`TC_TRUST_SCORING_BLIND_PACK`). That is the same allowed skip as master CI.

An earlier invocation of the same command, before the Playwright Chromium binary was installed locally, failed 3 browser tests (`test_domain_in_app_notifications.py`, `test_logout_all_browser.py`, `test_trust_requests_browser.py`) and passed the other 6391. Those 3 files then passed (39 tests) once `playwright install chromium` had downloaded the browser. The count above is the rerun with the browser present.

## Fail on parent, pass with the fix

Each new test was run against parent code at `a2b39c80` and failed. The same tests pass in the suite above.

| Test                                                                     | Parent                                                                   | With the fix |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------ | ------------ |
| `test_human_edited_llm_error_placeholder_survives_generation_retry`      | FAILED `Insufficient evidence.` overwrote the reviewer text              | PASSED       |
| `test_sweep_keeps_reviewer_edit_made_after_this_run_wrote`               | FAILED `assert 1 == 0` (sweep reclassified the edited draft)             | PASSED       |
| `test_post_answer_waits_on_question_lock_and_does_not_duplicate`         | FAILED `POST /answers did not wait for the question lock`                | PASSED       |
| `test_bulk_answer_waits_on_sorted_question_locks_and_does_not_duplicate` | FAILED `PATCH /answers/bulk did not wait for the question lock`          | PASSED       |
| `test_lease_heartbeat_renews_while_answer_batch_is_open`                 | FAILED `lease heartbeat could not renew while the answer batch was open` | PASSED       |

## Criterion, fix, test

| Criterion                                                                                | Fix                                                                                                                                                                                                                                                        | Test                                                                                                                                       |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| A human edit of an `llm_error` placeholder survives a generation retry.                  | `POST /answers` and `PATCH /answers/{id}` clear `insufficient_reason` when the text changes, so the placeholder exception no longer applies and the newer `updated_at` is kept.                                                                            | `test_human_edited_llm_error_placeholder_survives_generation_retry`                                                                        |
| A reviewer edit between this run's write and the sweep is not downgraded.                | `guard.written` maps question id to the timestamp the run stored. The sweep treats the row as this run's only while `updated_at` still equals that timestamp, and the UPDATE requires the same match.                                                      | `test_sweep_keeps_reviewer_edit_made_after_this_run_wrote`                                                                                 |
| `POST /answers` and `PATCH /answers/bulk` cannot each insert an answer for one question. | Both routes take the generation advisory lock before they read. Bulk locks question ids in sorted order. `docs/release/tickets/TC-10-003.md` no longer says a question has one answer row as a constraint, and it states that these routes share the lock. | `test_post_answer_waits_on_question_lock_and_does_not_duplicate`, `test_bulk_answer_waits_on_sorted_question_locks_and_does_not_duplicate` |
| A lease heartbeat can renew while a generation batch is open.                            | The answer insert is a Core statement inside a connection savepoint. It does not flush a dirty job row, so that row is not locked across the model call.                                                                                                   | `test_lease_heartbeat_renews_while_answer_batch_is_open`                                                                                   |

## Left out of scope

- One advisory lock per question can fill the shared lock table, and two jobs that lock questions in different orders can deadlock. A single lock per questionnaire would avoid both. Not changed.
- Approve and PATCH still have no version check, so a reviewer can approve text they never saw.
- Parse and index `FOR UPDATE` tests are still sequential rather than barrier threads.
- `isinstance(db, Session)` still skips the write guard for a session wrapper that is not a `Session` subclass.
- No unique index on `answers.question_id`. Product code no longer inserts a second answer row for a question. Only the test fixture at `apps/api/tests/test_evidence_gap_generation.py:688` creates one on purpose, to check that a sufficient row can't outvote a rejected or flagged one.
- Historical duplicate rows, if any, are not backfilled. Readers that build a dict from `question_id` can still see one of them.
- Pull request 105, the tracker, Jira, and backlog snapshots were not touched.
