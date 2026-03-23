"""Questionnaire AI mapping prefers subject areas (categories), not frameworks."""

from alembic import op
import sqlalchemy as sa


revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questionnaires",
        sa.Column("mapping_preferred_subject_areas_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questionnaires", "mapping_preferred_subject_areas_json")
