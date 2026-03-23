"""Questionnaire soft framework preference for AI control mapping.

Revision ID: 042
Revises: 041
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questionnaires",
        sa.Column("mapping_preferred_framework", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questionnaires", "mapping_preferred_framework")
