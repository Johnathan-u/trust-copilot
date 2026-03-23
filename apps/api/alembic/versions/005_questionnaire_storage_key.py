"""Add storage_key to questionnaires.

Revision ID: 005
Revises: 004
Create Date: 2025-01-01 00:04:00

"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("questionnaires", sa.Column("storage_key", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("questionnaires", "storage_key")
