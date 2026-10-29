# TC-02-BUG-018b Check constraints on evidence gap status and close_reason

**Epic:** E21 Compliance controls, mappings and gaps · **Type:** Bug follow-up (schema) · **Priority:** P3
**Origin:** Follow-up to TC-02-BUG-018a. `evidence_gaps.status` and `close_reason` were unconstrained strings.

## Problem

After TC-02-BUG-018 and TC-02-BUG-018a, a gap row can be `open`, `accepted`, `dismissed` or `resolved`, and `close_reason` is NULL or one of two codes. The columns are `varchar(20)` and `varchar(32)` with no check, so any other string that fits is stored.

## Values the code writes

Status, from `ALL_GAP_STATUSES` in `app/models/evidence_gap.py`:

| Value | Writer |
|---|---|
| `open` | Column default. `generate_gaps_for_questionnaire` inserts it. `update_evidence_gap_status` and `bulk_update_by_title` accept it. |
| `accepted` | `update_evidence_gap_status`, `bulk_update_by_title`. Both reject anything outside `GAP_STATUSES`. |
| `dismissed` | Same two helpers. |
| `resolved` | `generate_gaps_for_questionnaire` only, via `GAP_STATUS_RESOLVED`. The status helpers cannot set it. |

`close_reason`, from `GAP_CLOSE_REASONS` on the same model (the service aliases are `RESOLVED_QUESTION_REMOVED` and `RESOLVED_ANSWER_SUFFICIENT`):

| Value | Writer |
|---|---|
| NULL | New gaps. Open, accepted and dismissed rows that were never closed. The 018a backfill, when a resolved row's `reason` has no parseable note. |
| `question_removed` | Regeneration, when the question is gone. |
| `answer_sufficient` | Regeneration, when the question's answers are sufficient. |
| `evidence_sufficient` | Control-check scan (`CONTROL_CHECK_CLOSE_REASON` in PR #76). Not written by regeneration. |

No other application module assigns `EvidenceGap.status` or `EvidenceGap.close_reason`. `app/api/routes/evidence_gaps.py` is empty, and no route calls the status helpers. Nothing in the app writes a value outside this set, so no writer needed a source change. The service now takes the two closure codes from the model constants so the check and the writers share one definition.

## Checks

Revision `bug018b_gap_status_checks` (`apps/api/alembic/versions/bug018b_gap_status_checks.py`). `down_revision` is master's single head after TC-21-006, `tc21006_gap_evaluation`. The module does not import the application package. The same expressions are on `EvidenceGap.__table_args__`.

| Name | Expression |
|---|---|
| `ck_evidence_gaps_status` | `status IN ('open', 'accepted', 'dismissed', 'resolved')` |
| `ck_evidence_gaps_close_reason` | `close_reason IS NULL OR close_reason IN ('question_removed', 'answer_sufficient', 'evidence_sufficient')` |

Upgrade reads existing rows first. If any row would fail a check, it raises `EvidenceGapCheckViolation` with the constraint name, the full count, and up to five example ids, and it does not add the constraint or change a row. On a clean table each check is `ADD CONSTRAINT ... NOT VALID`, then `VALIDATE CONSTRAINT`, so the checks are validated against existing rows. `apps/api/alembic/env.py` runs the whole migration in one transaction, so both steps share that transaction and `NOT VALID` does not shorten the lock.

Downgrade drops only the two constraints. It does not rewrite rows, so it is lossless.

### Presence check, not added

`close_reason IS NOT NULL` only when `status = 'resolved'` is not a check. The code does not guarantee it.

- `update_evidence_gap_status` and `bulk_update_by_title` set `status` to `open`, `accepted` or `dismissed` and do not clear `close_reason`. `test_manual_status_changes_do_not_write_closure_columns` moves a resolved row to `open` and expects `close_reason` to stay `answer_sufficient`.
- The 018a backfill leaves `close_reason` NULL on resolved rows whose `reason` has no parseable note, and sets `closed_at` from `updated_at`. A rule that resolved rows must have a code would reject that history. This migration does not rewrite those rows.

The reason is `SKIPPED_PRESENCE_CHECK` in the revision module.

## Tests

`apps/api/tests/release/test_evidence_gap_status_checks.py`. Synthetic rows, the side `*_test` database, no network. The file passes `tests/release/test_safe_collection.py`.

An autouse fixture, same shape as the TC-21-005 tests, records `max(id)` and the row count for `evidence_gaps`, `questions`, `questionnaires`, `jobs`, `audit_events` and `workspaces` before each test. Teardown deletes every row with a higher id and requires the counts to match. It does not call `setval`.

| Test | Checks |
|---|---|
| `test_unknown_status_is_rejected` | `archived` violates `ck_evidence_gaps_status`. |
| `test_unknown_close_reason_is_rejected` | `not_a_code` violates `ck_evidence_gaps_close_reason`. |
| `test_values_the_app_writes_are_accepted` | Each status, and NULL plus both closure codes. |
| `test_non_resolved_row_may_keep_close_reason` | Open, accepted and dismissed rows may still hold a code. |
| `test_committed_gap_row_is_removed_after_the_test` | A committed gap is left in place. Teardown deletes it and the watched counts match. |
| `test_model_checks_match_the_migration` | Model SQL, names and literals match the revision. The revision does not import `app`. |
| `test_prescan_fails_on_violations_and_passes_on_clean_data` | A seeded violation fails the upgrade with counts and example ids, and the rows are unchanged. After those rows are deleted, the pre-scan is empty and upgrade adds validated checks. |
| `test_upgrade_downgrade_upgrade_round_trip` | Downgrade removes only the checks. Rows are unchanged across the round trip. |
| `test_revision_is_head_or_ancestor_of_every_head` | This revision is the head, or an ancestor of every head. |
| `test_offline_sql_adds_not_valid_then_validates` | `alembic --sql` emits NOT VALID, then VALIDATE, for both checks. Downgrade emits the two drops. Neither script writes rows. |

`test_values_the_app_writes_are_accepted`, `test_non_resolved_row_may_keep_close_reason` and `test_committed_gap_row_is_removed_after_the_test` also pass on master: those inserts already fit the unconstrained columns, and the teardown fixture travels with the test file. The other tests fail on master. The rejection tests insert a bad value that master stores. The migration tests fail because `bug018b_gap_status_checks.py` is not on master.

## Out of scope

- Clearing `close_reason` when a status helper moves a row off `resolved`, and then adding the presence check.
- Rewriting resolved rows whose `close_reason` is NULL.
- The partial unique index on open gaps per question.
