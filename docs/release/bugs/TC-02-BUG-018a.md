# TC-02-BUG-018a Record gap closure in dedicated columns

**Epic:** E21 Compliance controls, mappings and gaps · **Type:** Bug follow-up (schema) · **Priority:** P3
**Origin:** Ruling on TC-02-BUG-018. Filed only; not implemented.

## Problem

TC-02-BUG-018 closes stale evidence gaps without a migration. It records the closure by setting `status = "resolved"`, bumping `updated_at` and appending a delimited line to the free-text `reason`:

```text
[resolved on regeneration: <question_removed|answer_sufficient> at <UTC ISO-8601>Z]
```

That is enough for now but has limits:

- `updated_at` changes on any later edit, so it is not a reliable closure time.
- Closure reasons can only be queried by parsing `reason` text.
- `reason` mixes the opening explanation with closure history.

## Proposed change

1. Alembic migration (unique, descriptive revision id; re-parent onto master's head at merge time) adding to `evidence_gaps`:
   - `closed_at TIMESTAMP WITH TIME ZONE NULL`
   - `close_reason VARCHAR(64) NULL` (`question_removed`, `answer_sufficient`; room for later codes)
2. Backfill: for rows with `status = 'resolved'`, parse the last `[resolved on regeneration: <code> at <ts>]` line of `reason` into `close_reason` / `closed_at`; fall back to `updated_at` and leave `close_reason` NULL if the line is missing. Decide whether to strip the note from `reason` (default: keep it, the text is history).
3. `generate_gaps_for_questionnaire` writes `closed_at` and `close_reason` and stops appending to `reason`.
4. Expose both fields in the gap API payload (`_gap_to_dict`) and, if wanted, the gaps view.
5. Optional, separate decision: a check constraint on `status` values.

## Out of scope

- The partial unique index on open gaps per question (separate decision; needs a dedupe migration).
- Changing which gaps are closed (TC-02-BUG-018 rules stay).

## Acceptance criteria

- Migration upgrades and downgrades cleanly on the side test DB; a single alembic head.
- Backfill is idempotent and covered by a test with synthetic rows in both note formats and without a note.
- Regeneration writes `closed_at` / `close_reason`; existing TC-02-BUG-018 tests still pass with assertions moved to the new columns.
