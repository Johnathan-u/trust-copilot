"""Add message column to vendor_requests table.

Revision ID: 049
Revises: 048
"""

import sqlalchemy as sa
from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vendor_requests", sa.Column("message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("vendor_requests", "message")
