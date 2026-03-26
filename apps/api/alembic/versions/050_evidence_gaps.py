"""Create evidence_gaps table.

Revision ID: 050
Revises: 049
"""

from alembic import op
import sqlalchemy as sa

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    if "evidence_gaps" in sa_inspect(bind).get_table_names():
        return
    op.create_table(
        "evidence_gaps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "questionnaire_id",
            sa.Integer(),
            sa.ForeignKey("questionnaires.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "answer_id",
            sa.Integer(),
            sa.ForeignKey("answers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "gap_type", sa.String(64), nullable=False, server_default="missing_evidence"
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("proposed_policy_addition", sa.Text(), nullable=True),
        sa.Column("suggested_evidence_doc_title", sa.String(512), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="open", index=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("evidence_gaps")
