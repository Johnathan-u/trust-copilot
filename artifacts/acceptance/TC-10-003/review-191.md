# TC-10-003 review gaps (issue 191 comment 6711282482)

Parent: `3160f09` (`origin/master` when this branch was cut).
The suite below ran on the code in this commit. Filling in the commit SHA here would change the SHA, so the branch head is the commit that contains this file.

## Environment

- Python 3.11.18, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0
- PostgreSQL 16.15 with pgvector 0.6.0 from Ubuntu packages, database `trustcopilot_test` on `127.0.0.1`. CI uses the pinned `pgvector/pgvector:pg16` image (pgvector 0.8.7). This run is not that image.
- Node 24.22.1 so the backend suite's web-toolchain checks could run
- Synthetic rows only. Provider calls are patched. No model spend.

## Backend suite

```
cd apps/api
SESSION_SECRET=test-secret TC_REQUIRE_DB=1 TC_REQUIRE_WEB_TOOLCHAIN=1 TC_REQUIRE_API_QUALITY=1 \
  pytest -rs --tb=line -q
```

Exit 0. **6389 passed, 1 skipped, 51 warnings** in 578.39s.

The skip is `tests/test_trust_scoring_blind.py:33` (external blind pack not checked in). That is the same allowed skip as master CI.

`tests/release/test_job_idempotency.py` collects **52** tests (47 on the parent plus the 5 below). They passed inside this suite.

## Fail on parent, pass with the fix

Each new test was run against parent code at `3160f09` and failed. The same tests pass in the suite above.

| Test | Parent | With the fix |
|---|---|---|
| `test_upsert_keeps_approval_committed_after_reread_before_write` | FAILED `assert insufficient_evidence == approved` | PASSED |
| `test_sweep_keeps_approval_committed_after_guard_check` | FAILED `assert 1 == 0` (sweep reclassified the approved row) | PASSED |
| `test_stale_missing_answer_read_does_not_create_a_duplicate` | FAILED `assert 2 == 1` | PASSED |
| `test_question_lock_stops_a_second_generation_insert` | FAILED `generation did not wait for the question lock` | PASSED |
| `test_parse_crash_during_classification_records_uncertain_charge` | FAILED `DID NOT RAISE Crash` (classification swallowed the crash and recorded no charge) | PASSED |

## Criterion, fix, test

| Criterion | Fix | Test |
|---|---|---|
| AC2. A running generation must not overwrite an approval that commits after the re-read. | The answer UPDATE is conditional: `status` is not `approved`, and `updated_at` is not newer than the job, unless the row is an `llm_error` placeholder. Zero rows means the approval or newer edit is kept. The post-generation sweep uses the same predicate for real rows. | `test_upsert_keeps_approval_committed_after_reread_before_write`, `test_sweep_keeps_approval_committed_after_guard_check` |
| AC1. Two generation writes that both observed no answer must not insert two rows. | The writer takes `pg_advisory_xact_lock` for that question until its transaction ends, then reads again before inserting. A unique index was not added. `test_regeneration_keeps_gap_open_when_answer_is_rejected_or_flagged` inserts a second row on purpose so a sufficient row cannot outvote a rejected or flagged one. | `test_stale_missing_answer_read_does_not_create_a_duplicate`, `test_question_lock_stops_a_second_generation_insert` |
| AC2. Uncertainty about a parse-classification provider charge is recorded. | Before non-cached classification, `provider_call_started("openai_classify")` commits on its own connection. `settle` is in the same transaction as the signals. If that call is still `started` when classification raises, the exception propagates. The next claim's `reconcile_previous_attempts` marks it `uncertain`. Cached classification, and a failure before any call, still do not record a charge. | `test_parse_crash_during_classification_records_uncertain_charge` |
| DoD5. Migration rollback note was stale. | `docs/release/tickets/TC-10-003.md` now says `077`'s `down_revision` is `tc11001_model_outcome_codes`. Downgrading below `tc10003_job_idempotency` also reverts the 25 revisions above it, through `tc17003_security_claims`, and drops `job_effects`. TC-10-001 lease recovery calls `reconcile_previous_attempts` on that ledger. | Existing `test_migration_downgrade_and_upgrade_roundtrip` and `test_owner_token_migration_downgrade_and_upgrade_roundtrip` still pass. No schema change in this fix, so no new migration. |

## Left out of scope

- Independent acceptance (DoD5). The implementer does not record it, and `backlog-state.json` is not updated here.
- A unique index on `answers.question_id`, for the reason in the AC1 row.
- The review's note that parse and index `FOR UPDATE` tests are sequential rather than barrier threads. That note did not fail a criterion.
- Pull request 105. Not touched.
