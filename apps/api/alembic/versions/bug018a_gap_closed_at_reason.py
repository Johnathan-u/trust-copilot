"""Closure columns for evidence gaps (TC-02-BUG-018a).

Adds nullable ``closed_at`` (timestamptz) and ``close_reason`` (varchar(32)) to
``evidence_gaps``. Regeneration used to record a closure by appending a line to
``reason``. This revision copies that historical line onto the new columns and
does not change ``reason``.

Backfill, for ``status = 'resolved'`` only, reads the last line of ``reason``:

    [resolved on regeneration: <question_removed|answer_sufficient> at <UTC ISO>Z]

A matching line sets ``close_reason`` and ``closed_at``. Any other resolved row
gets ``closed_at = updated_at`` (naive ``updated_at`` is UTC) and a NULL
``close_reason``. Open, accepted and dismissed rows are not updated. Running the
statement again does not rewrite a row whose ``closed_at`` or ``close_reason``
is already set.

Downgrade is lossless. A row whose last ``reason`` line is already the note
is left untouched. A row that has ``closed_at`` and a known ``close_reason``
but no such last line gets that same note appended (or used as the whole
``reason`` when ``reason`` is NULL or empty) before the columns are dropped.
Upgrade can parse the note again. The note is whole UTC seconds, the same
grammar ``resolution_note()`` writes.

This module does not import the application package.

Revision ID: bug018a_gap_closed_at_reason
Revises: tc21003_evidence_link_uniq
"""

import sqlalchemy as sa
from alembic import op

revision = "bug018a_gap_closed_at_reason"
down_revision = "tc21003_evidence_link_uniq"
branch_labels = None
depends_on = None

# Same grammar as ``resolution_note()`` in evidence_gap_service.py. Python ``re`` and
# PostgreSQL accept this pattern. It contains no quotes.
NOTE_LINE_RE = (
    r"^\[resolved on regeneration: (question_removed|answer_sufficient) "
    r"at ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)\]$"
)

_TABLE = "evidence_gaps"

# __NOTE_RE__ is replaced with NOTE_LINE_RE. The pattern has no single quotes.
_BACKFILL_SQL = """
UPDATE evidence_gaps AS g
SET
    close_reason = parsed.code,
    closed_at = COALESCE(parsed.closed_at, g.updated_at AT TIME ZONE 'UTC')
FROM (
    SELECT
        id,
        note[1] AS code,
        CASE
            WHEN note[2] IS NULL THEN NULL
            ELSE note[2]::timestamptz
        END AS closed_at
    FROM (
        SELECT
            id,
            regexp_match(last_line, '__NOTE_RE__') AS note
        FROM (
            SELECT
                id,
                (regexp_split_to_array(COALESCE(reason, ''), E'\\n'))[
                    cardinality(regexp_split_to_array(COALESCE(reason, ''), E'\\n'))
                ] AS last_line
            FROM evidence_gaps
            WHERE status = 'resolved'
              AND closed_at IS NULL
              AND close_reason IS NULL
        ) AS lines
    ) AS matched
) AS parsed
WHERE g.id = parsed.id
  AND g.status = 'resolved'
  AND g.closed_at IS NULL
  AND g.close_reason IS NULL
"""


def backfill_sql() -> str:
    """SQL that fills the new columns. Idempotent; does not update ``reason``."""
    return _BACKFILL_SQL.replace("__NOTE_RE__", NOTE_LINE_RE)


# Append the historical note only when it is not already the last line of reason.
# Whole UTC seconds, so upgrade's NOTE_LINE_RE parses it back into the columns.
_PRESERVE_SQL = """
UPDATE evidence_gaps AS g
SET reason = CASE
    WHEN g.reason IS NULL OR g.reason = '' THEN note.line
    ELSE g.reason || E'\\n' || note.line
END
FROM (
    SELECT
        id,
        '[resolved on regeneration: ' || close_reason || ' at '
            || to_char(closed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
            || 'Z]' AS line
    FROM evidence_gaps
    WHERE closed_at IS NOT NULL
      AND close_reason IN ('question_removed', 'answer_sufficient')
) AS note
WHERE g.id = note.id
  AND (
        g.reason IS NULL
        OR (regexp_split_to_array(g.reason, E'\\n'))[
            cardinality(regexp_split_to_array(g.reason, E'\\n'))
        ] IS DISTINCT FROM note.line
      )
"""


def preserve_sql() -> str:
    """SQL that copies closure columns back into ``reason`` before they are dropped."""
    return _PRESERVE_SQL


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column("close_reason", sa.String(32), nullable=True),
    )
    op.execute(sa.text(backfill_sql()))


def downgrade() -> None:
    op.execute(sa.text(preserve_sql()))
    op.drop_column(_TABLE, "close_reason")
    op.drop_column(_TABLE, "closed_at")
