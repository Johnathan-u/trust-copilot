"""Add optional attachment to trust requests (public form upload).

Revision ID: 021
Revises: 020
Create Date: 2025-03-14

"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trust_requests", sa.Column("attachment_filename", sa.String(255), nullable=True))
    op.add_column("trust_requests", sa.Column("attachment_storage_key", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("trust_requests", "attachment_storage_key")
    op.drop_column("trust_requests", "attachment_filename")
