"""Questionnaire-scoped answer evidence (document allowlist for AI answers).

Revision ID: 043
Revises: 042
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questionnaires",
        sa.Column("answer_evidence_document_ids_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questionnaires", "answer_evidence_document_ids_json")
