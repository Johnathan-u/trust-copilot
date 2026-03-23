"""Trust request notes (TC-H-B2).

Revision ID: 018
Revises: 017
Create Date: 2026-03-14

"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trust_request_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trust_request_id", sa.Integer(), sa.ForeignKey("trust_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_trust_request_notes_trust_request_id", "trust_request_notes", ["trust_request_id"])


def downgrade() -> None:
    op.drop_table("trust_request_notes")
