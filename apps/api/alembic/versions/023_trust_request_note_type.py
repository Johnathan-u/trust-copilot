"""TC-H-B2: Add note_type to trust_request_notes (internal_note vs reply).

Revision ID: 023
Revises: 022
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trust_request_notes",
        sa.Column("note_type", sa.String(32), nullable=False, server_default="internal_note"),
    )


def downgrade() -> None:
    op.drop_column("trust_request_notes", "note_type")
