"""Refuse moving a parent into another workspace while a child still points at it (TC-02-BUG-001a).

The child-side triggers in tc06001_same_workspace_refs do not run when the parent row's
workspace changes. These BEFORE UPDATE triggers close that side for documents, questionnaires,
questions and answers. Existing cross-workspace rows are not rewritten. An update that does
not change the workspace column is not checked.

Revision ID: tc02001a_parent_ws_move
Revises: tc21006_gap_evaluation
"""

from alembic import op

revision = "tc02001a_parent_ws_move"
down_revision = "tc21006_gap_evaluation"
branch_labels = None
depends_on = None

_REJECT = "RAISE EXCEPTION 'parent workspace move rejected' USING ERRCODE = '23514';"


def _fn(name: str, body: str, table: str, columns: str) -> None:
    op.execute(
        f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$\n"
        f"BEGIN\n{body}  RETURN NEW;\nEND\n$$;"
    )
    op.execute(f"DROP TRIGGER IF EXISTS trg_{name} ON {table};")
    op.execute(
        f"CREATE TRIGGER trg_{name} BEFORE UPDATE OF {columns} ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {name}();"
    )


def upgrade() -> None:
    _fn(
        "tc_parent_ws_documents",
        "  IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id AND EXISTS (\n"
        "    SELECT 1 FROM evidence_items e\n"
        "    WHERE e.document_id = NEW.id AND e.workspace_id IS DISTINCT FROM NEW.workspace_id\n"
        "  ) THEN\n"
        f"    {_REJECT}\n"
        "  END IF;\n",
        "documents",
        "workspace_id",
    )
    _fn(
        "tc_parent_ws_questionnaires",
        "  IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id AND (\n"
        "    EXISTS (SELECT 1 FROM export_records x WHERE x.questionnaire_id = NEW.id\n"
        "            AND x.workspace_id IS DISTINCT FROM NEW.workspace_id)\n"
        "    OR EXISTS (SELECT 1 FROM evidence_gaps g WHERE g.questionnaire_id = NEW.id\n"
        "               AND g.workspace_id IS DISTINCT FROM NEW.workspace_id)\n"
        "    OR EXISTS (SELECT 1 FROM evidence_gaps g JOIN questions q ON q.id = g.question_id\n"
        "               WHERE q.questionnaire_id = NEW.id\n"
        "               AND g.workspace_id IS DISTINCT FROM NEW.workspace_id)\n"
        "    OR EXISTS (SELECT 1 FROM evidence_gaps g\n"
        "               JOIN answers a ON a.id = g.answer_id\n"
        "               JOIN questions q ON q.id = a.question_id\n"
        "               WHERE q.questionnaire_id = NEW.id\n"
        "               AND g.workspace_id IS DISTINCT FROM NEW.workspace_id)\n"
        "  ) THEN\n"
        f"    {_REJECT}\n"
        "  END IF;\n",
        "questionnaires",
        "workspace_id",
    )
    _fn(
        "tc_parent_ws_questions",
        "  IF NEW.questionnaire_id IS DISTINCT FROM OLD.questionnaire_id AND EXISTS (\n"
        "    SELECT 1 FROM evidence_gaps g\n"
        "    JOIN questionnaires qn ON qn.id = NEW.questionnaire_id\n"
        "    WHERE g.question_id = NEW.id AND g.workspace_id IS DISTINCT FROM qn.workspace_id\n"
        "  ) THEN\n"
        f"    {_REJECT}\n"
        "  END IF;\n",
        "questions",
        "questionnaire_id",
    )
    _fn(
        "tc_parent_ws_answers",
        "  IF NEW.question_id IS DISTINCT FROM OLD.question_id AND EXISTS (\n"
        "    SELECT 1 FROM evidence_gaps g\n"
        "    JOIN questions q ON q.id = NEW.question_id\n"
        "    JOIN questionnaires qn ON qn.id = q.questionnaire_id\n"
        "    WHERE g.answer_id = NEW.id AND g.workspace_id IS DISTINCT FROM qn.workspace_id\n"
        "  ) THEN\n"
        f"    {_REJECT}\n"
        "  END IF;\n",
        "answers",
        "question_id",
    )


def downgrade() -> None:
    for name, table in (
        ("tc_parent_ws_answers", "answers"),
        ("tc_parent_ws_questions", "questions"),
        ("tc_parent_ws_questionnaires", "questionnaires"),
        ("tc_parent_ws_documents", "documents"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{name} ON {table};")
        op.execute(f"DROP FUNCTION IF EXISTS {name}();")
