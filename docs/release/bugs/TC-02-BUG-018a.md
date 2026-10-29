# TC-02-BUG-018a Record gap closure in dedicated columns

**Epic:** E21 Compliance controls, mappings and gaps · **Type:** Bug follow-up (schema) · **Priority:** P3
**Origin:** Ruling on TC-02-BUG-018. Implemented on `tc/core/TC-02-BUG-018a`.

## Problem

TC-02-BUG-018 closes stale evidence gaps without a migration. It records the closure by setting `status = "resolved"`, bumping `updated_at` and appending a delimited line to the free-text `reason`:

```text
[resolved on regeneration: <question_removed|answer_sufficient> at <UTC ISO-8601>Z]
```

That was enough to ship the close, and it has limits:

- `updated_at` changes on any later edit, so it is not a reliable closure time.
- Closure reasons can only be queried by parsing `reason` text.
- `reason` mixes the opening explanation with closure history.

## Design

`generate_gaps_for_questionnaire` still closes the same rows, under the same `pg_advisory_xact_lock(150015, questionnaire_id)`, and still never deletes them. Closing now writes:

| Column | Type | Value |
|---|---|---|
| `closed_at` | `TIMESTAMP WITH TIME ZONE` NULL | Closure time (UTC). |
| `close_reason` | `VARCHAR(32)` NULL | `question_removed` or `answer_sufficient`. |

`reason` is not modified. The original opening text stays byte for byte, including any historical note already stored there. A new open gap for a question that becomes insufficient again does not copy these columns; the resolved row stays as history with its `closed_at` and `close_reason`.

Only that close writes the columns. `update_evidence_gap_status` and `bulk_update_by_title` change `status` and `updated_at` and leave `closed_at` / `close_reason` alone. Accepted and dismissed gaps are still never closed or reopened by regeneration, and `llm_error` / `model_*` placeholders still neither open nor close a gap.

`_gap_to_dict` (used by `list_evidence_gaps`, `get_evidence_gap` and `update_evidence_gap_status`) adds `closed_at` and `close_reason`. Existing keys stay.

No API route sets a resolved gap back to `open`. The status helpers exist on the service and are not mounted under `app/api`. See TC-02-BUG-018, resolved decision 5.

`VARCHAR(32)` holds the two codes (16 and 17 characters) with room for another short code. A longer code would be a follow-up that widens the column. There is no check constraint on `close_reason` or `status`.

## Migration

Revision `bug018a_gap_closed_at_reason` (`apps/api/alembic/versions/bug018a_gap_closed_at_reason.py`). `down_revision` is master's single head at push, `tc21002a_canonical_uniq` (TC-21-002a landed on master after this branch started from `bug019_article_slug_ws`). The module does not import the application package.

Upgrade adds the two nullable columns, then backfills. Downgrade drops `close_reason` and `closed_at`. It does not rewrite `reason` and does not rebuild a note for rows closed after this revision, so a downgrade drops the closure time and code for those rows.

### Backfill

Only `status = 'resolved'` rows whose `closed_at` and `close_reason` are both still NULL are updated. The last line of `reason` is matched against the historical note grammar (`NOTE_LINE_RE`, the same string `resolution_note()` writes):

- Match: `close_reason` is the code and `closed_at` is the `Z` timestamp.
- No match (missing line, NULL `reason`, or a code other than the two known ones): `close_reason` stays NULL and `closed_at` is `updated_at` interpreted as UTC (`AT TIME ZONE 'UTC'`), so the session TimeZone does not move it.
- An earlier note line that is not the last line is ignored. The last line wins.
- Open, accepted and dismissed rows are not updated, even if `reason` contains a note.
- `reason` is never written.

Running the statement again does not change a row that already has `closed_at` or `close_reason` set. A later edit of `updated_at` does not move `closed_at`.

## Tests

`apps/api/tests/release/test_evidence_gap_closure_columns.py`, plus the TC-02-BUG-018 regeneration tests, whose closure assertions now read the columns. Synthetic rows, the side `*_test` database, no network. `tests/release/test_gap_totals_exclude_resolved.py` no longer calls `setval` on the workspaces sequence; it inserts explicit primary keys so it does not touch shared serial sequences. The totals assertions are unchanged.

| Test | Checks |
|---|---|
| `test_closing_sets_columns_when_answer_becomes_sufficient` | `answer_sufficient`, `closed_at` set, reason unchanged, the other gap stays open with NULL columns. |
| `test_closing_sets_columns_when_question_is_removed` | `question_removed`, reason unchanged. |
| `test_closing_preserves_reason_text_including_an_embedded_note` | A reason that already contains a note is kept byte for byte. The column code comes from the answer, not from that text. |
| `test_accepted_and_dismissed_gaps_keep_null_closure_columns` | Accepted and dismissed rows are untouched, including the new columns. |
| `test_llm_error_placeholder_does_not_write_closure_columns` | Placeholders neither open nor close a gap. |
| `test_manual_status_changes_do_not_write_closure_columns` | Status helpers do not fill the columns, and do not clear them on a resolved row. |
| `test_reinsufficient_question_keeps_the_resolved_row` | A new open gap; the resolved row keeps its columns. |
| `test_gap_payload_exposes_closure_columns` | Both fields are in the gap dict; existing keys remain. |
| `test_historical_note_matches_the_backfill_pattern` | `resolution_note()` output matches `NOTE_LINE_RE`. The migration does not import `app`. |
| `test_backfill_parses_old_notes_and_falls_back_to_updated_at` | Both note codes, last-line wins, note-only reason, missing note, malformed code, NULL reason, and non-resolved rows. Idempotent re-run. Downgrade keeps `reason`; upgrade parses it again. |
| `test_migration_upgrade_downgrade_upgrade_round_trip` | Columns exist, go away, and come back. Types are timestamptz and `varchar(32)`, both nullable. One alembic head. |
| `test_offline_sql_adds_and_drops_the_columns` | `alembic upgrade` / `downgrade` `--sql` emits the add, the backfill, and the drops. |

## Out of scope

- The partial unique index on open gaps per question (separate decision; needs a dedupe migration).
- Changing which gaps are closed (TC-02-BUG-018 rules stay).
- A check constraint on `status` or `close_reason`.
- Stripping historical notes out of `reason`.
- Rebuilding the note on downgrade.

## Acceptance criteria

- Migration upgrades and downgrades cleanly on the side test DB; a single alembic head.
- Backfill is idempotent and covered by a test with synthetic rows in both note formats and without a note.
- Regeneration writes `closed_at` / `close_reason`; existing TC-02-BUG-018 tests still pass with assertions moved to the new columns.
