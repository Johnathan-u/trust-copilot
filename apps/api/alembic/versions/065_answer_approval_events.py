"""answer approval events and golden_answers reviewer columns

Revision ID: 065
Revises: 064
"""
from alembic import op
import sqlalchemy as sa

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answer_approval_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("golden_answer_id", sa.Integer(), sa.ForeignKey("golden_answers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("golden_answers", sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("golden_answers", sa.Column("review_sla_hours", sa.Integer(), nullable=True, server_default="48"))
    op.add_column("golden_answers", sa.Column("submitted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("golden_answers", "submitted_at")
    op.drop_column("golden_answers", "review_sla_hours")
    op.drop_column("golden_answers", "reviewer_user_id")
    op.drop_table("answer_approval_events")
