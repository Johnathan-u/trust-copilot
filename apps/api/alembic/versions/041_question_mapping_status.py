"""Add status and updated_at to question_mapping_preferences for questionnaire mapping flow.

Revision ID: 041
Revises: 040
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "question_mapping_preferences",
        sa.Column("status", sa.String(32), nullable=False, server_default="suggested"),
    )
    op.add_column(
        "question_mapping_preferences",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("question_mapping_preferences", "updated_at")
    op.drop_column("question_mapping_preferences", "status")
