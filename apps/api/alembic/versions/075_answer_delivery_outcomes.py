"""Answer delivery outcome tags (E6-31)

Revision ID: 075
Revises: 074
"""

from alembic import op
import sqlalchemy as sa

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answer_delivery_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "answer_id",
            sa.Integer(),
            sa.ForeignKey("answers.id", ondelete="CASCADE"),
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
            "deal_id",
            sa.Integer(),
            sa.ForeignKey("deals.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "golden_answer_id",
            sa.Integer(),
            sa.ForeignKey("golden_answers.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("accepted_without_edits", sa.Boolean(), nullable=True),
        sa.Column("was_edited", sa.Boolean(), nullable=True),
        sa.Column("edit_diff_json", sa.Text(), nullable=True),
        sa.Column("follow_up_requested", sa.Boolean(), nullable=True),
        sa.Column("buyer_pushback", sa.Boolean(), nullable=True),
        sa.Column("deal_closed", sa.Boolean(), nullable=True),
        sa.Column("review_cycle_hours", sa.Float(), nullable=True),
        sa.Column("channel", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_answer_outcome_workspace_answer",
        "answer_delivery_outcomes",
        ["workspace_id", "answer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_answer_outcome_workspace_answer", table_name="answer_delivery_outcomes")
    op.drop_table("answer_delivery_outcomes")
