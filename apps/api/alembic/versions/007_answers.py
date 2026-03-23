"""Answers table (AI-05).

Revision ID: 007
Revises: 006
Create Date: 2025-01-01 00:07:00

"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), server_default="draft"),
        sa.Column("citations", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_answers_question_id", "answers", ["question_id"])


def downgrade() -> None:
    op.drop_table("answers")
