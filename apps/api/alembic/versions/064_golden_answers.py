"""Create golden_answers table.

Revision ID: 064
Revises: 063
"""
from alembic import op
import sqlalchemy as sa

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    if "golden_answers" in sa_inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "golden_answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("control_ids_json", sa.Text(), nullable=True),
        sa.Column("evidence_ids_json", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), default="approved", nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_cycle_days", sa.Integer(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("reuse_count", sa.Integer(), default=0, nullable=False),
        sa.Column("source_answer_id", sa.Integer(), nullable=True),
        sa.Column("customer_override_for", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("golden_answers")
