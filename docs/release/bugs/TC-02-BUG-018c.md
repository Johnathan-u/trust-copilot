# TC-02-BUG-018c One open gap per question

**Epic:** E21 Compliance controls, mappings and gaps · **Type:** Bug follow-up (schema) · **Priority:** P2
**Origin:** Follow-up from TC-02-BUG-018. Implemented on `tc/core/TC-02-BUG-018c`.

## Problem

`generate_gaps_for_questionnaire` keeps a single open `missing_evidence` gap per question inside `pg_advisory_xact_lock(150015, questionnaire_id)`. That is application state. Nothing in Postgres rejected a second `status = 'open'` row for the same question if another writer committed one, or if `update_evidence_gap_status` set a second row to `open`.

## Design

Partial unique index `uq_evidence_gaps_one_open_per_question` on `evidence_gaps (workspace_id, questionnaire_id, question_id)`:

```sql
WHERE status = 'open'
  AND question_id IS NOT NULL
  AND gap_type <> 'control_check'
```

`workspace_id`, `questionnaire_id` and `question_id` are the scope the generator uses: it loads gaps for one workspace and questionnaire, then treats `question_id` as the key. The open literal is `open` (`GAP_STATUS_OPEN`).

The same index is on `EvidenceGap.__table_args__` (`Index` with `postgresql_where`).

TC-21-006 (`_persist_control_checks` on `tc/ca/TC-21-006`) inserts open `gap_type = 'control_check'` rows and does not set `question_id` or `questionnaire_id`. A workspace can have several of those open at once, one per `control_id`. They are not one-open-gap-per-question. `close_reason = 'evidence_sufficient'` is written only when a scan row is resolved, so that value is never on a row this index covers. The predicate leaves those open scan rows out.

`questionnaire_id` is nullable. PostgreSQL does not treat NULL as equal, so two open questionnaire rows with a NULL `questionnaire_id` do not collide. The pre-scan ignores them for the same reason. A NULL `question_id` is not a question (the FK is `ON DELETE SET NULL`) and is not in the index.

Accepted and dismissed rows are outside the predicate. The generator still treats them as covering the question and does not open a second gap.

Downgrade drops only the index. It does not rewrite rows.

The revision id `bug018c_one_open_gap` is 20 characters, so it fits `alembic_version.version_num` (`varchar(32)`). This revision does not alter that column. Downgrade drops only the index.

## Migration

Revision `bug018c_one_open_gap` (`apps/api/alembic/versions/bug018c_one_open_gap.py`). `down_revision` is master's Alembic head at push. The module does not import the application package.

Before `CREATE UNIQUE INDEX`, upgrade counts questions that already have more than one open row inside the index predicate. A hit raises `OpenGapDuplicate` with the question count, the open-row count and example gap ids (at most five), and creates nothing. It does not delete or close rows.

`DEDUPE_SQL` in that module is the statement an operator can run first. It keeps the newest open row (highest id) for each `(workspace_id, questionnaire_id, question_id)` and sets the older ones to `status = 'resolved'` with `closed_at` and `updated_at`. It does not delete rows. It does not set `close_reason` to `superseded` (the application does not write that code) or to `evidence_sufficient` (that code means a scan found qualifying evidence). `close_reason` stays as it was, which is NULL on a row that was never closed. Scan rows are not updated. The migration does not execute this statement.

Offline `alembic --sql` skips the pre-scan. There is no database to read.

## App behaviour

`generate_gaps_for_questionnaire` still takes the advisory lock before it reads, and it still skips a question that already has an open, accepted or dismissed gap. Closes are flushed before inserts. Each insert runs in a savepoint. If this index rejects it, the insert alone is rolled back and the question is treated as already open. The closes in that transaction still commit.

`update_evidence_gap_status(..., "open")` does not take the lock. If the index rejects that update, the requested row is left unchanged and the existing open gap for that question is returned. Any other integrity error still propagates.

`bulk_update_by_title` only updates rows that are already `open`, so it does not add a second open row.

## Tests

`apps/api/tests/release/test_evidence_gap_one_open_index.py`. Synthetic rows, the side `*_test` database, no network. Each test records `max(id)` and the row count for `evidence_gaps`, `answers`, `questions`, `questionnaires`, `jobs`, `audit_events` and `workspaces`, deletes rows above that id, and requires the counts to match. It does not call `setval`.

| Test | Checks |
|---|---|
| `test_second_open_gap_for_the_same_question_is_rejected` | A second open row for one question raises. A different question may still be open. |
| `test_open_and_resolved_for_the_same_question_are_allowed` | Open plus resolved for one question. |
| `test_several_open_control_checks_with_null_question_are_allowed` | Three open `control_check` rows with a null question. |
| `test_generation_still_opens_one_gap_and_can_open_again_after_resolve` | One open gap, a rerun, a close, then a new open row after the answer is insufficient again. |
| `test_generation_treats_unique_violation_as_already_open` | A gap committed after the read does not raise. One open row remains. |
| `test_status_update_treats_unique_violation_as_already_open` | Reopening a resolved row while another is open returns the open row and leaves the resolved row. |
| `test_model_index_matches_the_migration` | Name, columns, predicate, and no application import in the revision. |
| `test_prescan_fails_on_duplicate_open_gaps_and_passes_on_clean_data` | Duplicates fail the upgrade and are unchanged, including scan rows. Clean data upgrades. |
| `test_documented_dedupe_closes_older_rows_without_deleting` | Operator SQL keeps the newest open row, does not delete, and does not touch scan rows. |
| `test_upgrade_downgrade_upgrade_round_trip` | Index drops and returns. Rows are unchanged. |
| `test_revision_is_head_or_ancestor_of_every_head` | This revision or any descendant. |
| `test_offline_sql_creates_partial_unique_index_and_downgrade_drops_it` | Upgrade SQL is the partial index. Downgrade drops it. No row rewrite. |
| `test_committed_gap_row_is_removed_after_the_test` | Teardown deletes a committed row above the watermark. |

## Acceptance criteria

- At most one open gap per question inside a workspace and questionnaire. Open plus resolved is allowed.
- Open `control_check` rows with a null `question_id` are not rejected and are not treated as duplicates by the pre-scan.
- Existing duplicates fail the upgrade with counts and sample ids. No row is deleted or closed by the migration.
- Downgrade drops only the index.
- The generator still opens one gap per insufficient question and does not raise `IntegrityError` for this index under the advisory lock. A conflict that still occurs is treated as already open.

## Open questions

`update_evidence_gap_status` treats a unique violation as already open by returning the other open gap's dict. The caller sees that row's id, and nothing in the payload says it is a different row from the one requested. That should be a 409 once a route calls this helper. The helper's return value is unchanged until then.

When #76 (`tc21006_gap_evaluation`) and #78 (`bug018b_gap_status_checks`) have merged, this revision should re-parent onto `bug018b_gap_status_checks`. `GAP_TYPE_CONTROL_CHECK` should then be the same constant as #76's `CONTROL_CHECK`. Not done in this change. Parent remains master's current head.
