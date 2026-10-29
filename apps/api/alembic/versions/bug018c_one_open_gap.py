"""One open evidence gap per question (TC-02-BUG-018c).

``evidence_gaps`` may hold many rows for one question. Regeneration already
keeps a single open ``missing_evidence`` gap inside
``pg_advisory_xact_lock(150015, questionnaire_id)``. This revision adds the
same rule in the database for every writer: at most one row with
``status = 'open'`` for a ``(workspace_id, questionnaire_id, question_id)``.

The partial predicate is ``status = 'open' AND question_id IS NOT NULL AND
gap_type <> 'control_check'``. TC-21-006 scan rows are ``gap_type =
'control_check'`` with ``question_id`` left NULL, and a workspace keeps
several of them open at once (one per control). They are not one-per-question.
``close_reason = 'evidence_sufficient'`` is written only when a scan row is
resolved, so it never qualifies for this index.

``questionnaire_id`` is nullable. PostgreSQL unique indexes treat NULL as
distinct, so the pre-scan also ignores a NULL questionnaire. It does not
report scan rows, NULL questions, or a single open row.

Upgrade counts questions that already have more than one open gap inside
that predicate. A hit raises with the question count, the open-row count and
example gap ids, and creates nothing. It does not delete or close rows.
``DEDUPE_SQL`` is the statement an operator can run first. It keeps the newest
open row (highest id) and closes the older ones with ``status = 'resolved'``.
It does not set ``close_reason`` to ``superseded`` or ``evidence_sufficient``.
The application writes ``question_removed`` and ``answer_sufficient`` for
questionnaire closes, and ``evidence_sufficient`` only for a scan close. NULL
``close_reason`` on a resolved row is what the 018a backfill already leaves
when a note is missing. The statement is not executed here. Scan rows are
not in it.

Downgrade drops only the index. The revision id fits ``alembic_version.version_num``
(``varchar(32)``), so this revision does not alter that column.

This module does not import the application package. Tests lock these
literals to the model.

Revision ID: bug018c_one_open_gap
Revises: bug018b_gap_status_checks
"""

import sqlalchemy as sa
from alembic import context, op

revision = "bug018c_one_open_gap"
down_revision = "bug018b_gap_status_checks"
branch_labels = None
depends_on = None

_TABLE = "evidence_gaps"
# How many violating gap ids to print. The counts in the error are the full counts.
EXAMPLE_LIMIT = 5

OPEN_STATUS = "open"
EXCLUDED_GAP_TYPE = "control_check"
INDEX_NAME = "uq_evidence_gaps_one_open_per_question"
INDEX_COLUMNS = ("workspace_id", "questionnaire_id", "question_id")
INDEX_WHERE = "status = 'open' AND question_id IS NOT NULL AND gap_type <> 'control_check'"

# Not executed. Keeps the newest open questionnaire row for each question and
# closes older open rows. Rows stay. close_reason is left as it was. Scan rows
# (control_check, or a null question) are not updated.
DEDUPE_SQL = """
UPDATE evidence_gaps AS g
SET
    status = 'resolved',
    closed_at = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
WHERE g.status = 'open'
  AND g.question_id IS NOT NULL
  AND g.questionnaire_id IS NOT NULL
  AND g.gap_type <> 'control_check'
  AND g.id <> (
      SELECT MAX(newer.id)
      FROM evidence_gaps AS newer
      WHERE newer.status = 'open'
        AND newer.workspace_id = g.workspace_id
        AND newer.questionnaire_id = g.questionnaire_id
        AND newer.question_id = g.question_id
        AND newer.gap_type <> 'control_check'
  )
"""


def _checked_literal(value: str, label: str) -> str:
    if not value or any(ch in value for ch in "'\\"):
        raise RuntimeError(f"refusing unsafe {label} literal: {value!r}")
    return value


_SCAN_SQL = f"""
WITH grouped AS (
    SELECT count(*) AS n, array_agg(id ORDER BY id) AS ids
    FROM {_TABLE}
    WHERE status = '{_checked_literal(OPEN_STATUS, "open-status")}'
      AND question_id IS NOT NULL
      AND questionnaire_id IS NOT NULL
      AND gap_type <> '{_checked_literal(EXCLUDED_GAP_TYPE, "gap-type")}'
    GROUP BY workspace_id, questionnaire_id, question_id
    HAVING count(*) > 1
)
SELECT
    CAST(count(*) AS integer) AS questions,
    CAST(COALESCE(sum(n), 0) AS integer) AS open_rows,
    COALESCE(
        (
            SELECT array_agg(picked.id ORDER BY picked.id)
            FROM (
                SELECT flat.id
                FROM (
                    SELECT unnest(ids) AS id
                    FROM grouped
                ) AS flat
                ORDER BY flat.id
                LIMIT {int(EXAMPLE_LIMIT)}
            ) AS picked
        ),
        CAST(ARRAY[] AS integer[])
    ) AS example_ids
FROM grouped
"""


class OpenGapDuplicate(RuntimeError):
    """More than one open gap exists for a question. No row was modified."""

    def __init__(self, questions: int, open_rows: int, example_ids: list[int]):
        self.questions = questions
        self.open_rows = open_rows
        self.example_ids = example_ids
        shown = ", ".join(str(gap_id) for gap_id in example_ids)
        super().__init__(
            "evidence_gaps one-open-gap pre-scan failed. No rows were changed. "
            f"Refusing to create {INDEX_NAME}.\n"
            f"{questions} question(s) have more than one open gap "
            f"({open_rows} open row(s)). Example gap ids: {shown}.\n"
            "Operator dedupe (not run by this migration). It keeps the newest "
            "open row and closes the older ones. It does not delete rows and "
            "does not set close_reason to 'superseded'.\n" + DEDUPE_SQL.strip()
        )


def _example_ids(value: object) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        inner = value.strip("{}")
        if not inner:
            return []
        return [int(part) for part in inner.split(",") if part]
    return [int(item) for item in value]  # type: ignore[union-attr]


def duplicate_open_gaps(connection) -> tuple[int, int, list[int]]:
    """Questions with more than one open gap. Empty when the table is clean. Reads only.

    NULL ``question_id``, NULL ``questionnaire_id`` and ``control_check`` rows
    are excluded. A unique index does not reject those rows, so failing the
    migration on them would stop an upgrade that ``CREATE UNIQUE INDEX``
    would accept. Scan rows are open per control, not per question.
    """
    row = connection.execute(sa.text(_SCAN_SQL)).one()
    questions = int(row[0])
    open_rows = int(row[1])
    return questions, open_rows, _example_ids(row[2])


def upgrade() -> None:
    # Offline --sql has no rows to scan. Online, refuse before any DDL.
    if not context.is_offline_mode():
        questions, open_rows, example_ids = duplicate_open_gaps(op.get_bind())
        if questions:
            raise OpenGapDuplicate(questions, open_rows, example_ids)
    if INDEX_WHERE != (
        "status = 'open' AND question_id IS NOT NULL AND gap_type <> 'control_check'"
    ):
        raise RuntimeError(f"refusing unexpected partial index predicate: {INDEX_WHERE!r}")
    op.create_index(
        INDEX_NAME,
        _TABLE,
        list(INDEX_COLUMNS),
        unique=True,
        postgresql_where=sa.text(INDEX_WHERE),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=_TABLE)
