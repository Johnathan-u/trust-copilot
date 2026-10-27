"""Same-workspace triggers for evidence_items, export_records and evidence_gaps (TC-06-BUG-001)

The existing foreign keys only prove the referenced row exists. These BEFORE INSERT / UPDATE OF
triggers also require it to sit in the row's own workspace. Questions and answers have no
workspace_id, so their ownership is resolved through questionnaires.

Only new writes are checked. An UPDATE fires the trigger only when it sets one of the listed
columns, so existing rows (including any legacy cross-workspace rows) are never re-validated and
this upgrade cannot fail on them. NULL references are allowed, which keeps ON DELETE SET NULL
working. No data is read, changed or deleted by this revision.

Revision ID: tc06001_same_workspace_refs
Revises: tc25005_case_study_consent
"""

from alembic import op

revision = "tc06001_same_workspace_refs"
down_revision = "tc25005_case_study_consent"
branch_labels = None
depends_on = None

# Frozen SQL; this module must not import the application package.
_REJECT = "RAISE EXCEPTION 'cross-workspace reference rejected' USING ERRCODE = '23503';"

_Q_WS = "SELECT qn.workspace_id FROM questionnaires qn WHERE qn.id = {ref}"
_QUESTION_WS = (
    "SELECT qn.workspace_id FROM questions q JOIN questionnaires qn ON qn.id = q.questionnaire_id"
    " WHERE q.id = {ref}"
)
_ANSWER_WS = (
    "SELECT qn.workspace_id FROM answers a JOIN questions q ON q.id = a.question_id"
    " JOIN questionnaires qn ON qn.id = q.questionnaire_id WHERE a.id = {ref}"
)
_DOC_WS = "SELECT d.workspace_id FROM documents d WHERE d.id = {ref}"


def _guard(column: str, lookup: str) -> str:
    sub = lookup.format(ref=f"NEW.{column}")
    return (
        f"  IF NEW.{column} IS NOT NULL AND NEW.workspace_id IS DISTINCT FROM ({sub}) THEN\n"
        f"    {_REJECT}\n"
        f"  END IF;\n"
    )


_TRIGGERS = (
    ("evidence_items", (("document_id", _DOC_WS),)),
    ("export_records", (("questionnaire_id", _Q_WS),)),
    (
        "evidence_gaps",
        (
            ("questionnaire_id", _Q_WS),
            ("question_id", _QUESTION_WS),
            ("answer_id", _ANSWER_WS),
        ),
    ),
)


def _fn(table: str) -> str:
    return f"tc_same_ws_{table}"


def upgrade() -> None:
    for table, guards in _TRIGGERS:
        body = "".join(_guard(col, lookup) for col, lookup in guards)
        cols = ", ".join(["workspace_id", *(col for col, _ in guards)])
        op.execute(
            f"CREATE OR REPLACE FUNCTION {_fn(table)}() RETURNS trigger LANGUAGE plpgsql AS $$\n"
            f"BEGIN\n{body}  RETURN NEW;\nEND\n$$;"
        )
        op.execute(f"DROP TRIGGER IF EXISTS trg_{_fn(table)} ON {table};")
        op.execute(
            f"CREATE TRIGGER trg_{_fn(table)} BEFORE INSERT OR UPDATE OF {cols} ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_fn(table)}();"
        )


def downgrade() -> None:
    for table, _ in reversed(_TRIGGERS):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{_fn(table)} ON {table};")
        op.execute(f"DROP FUNCTION IF EXISTS {_fn(table)}();")
