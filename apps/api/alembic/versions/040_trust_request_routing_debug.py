"""Add routing debug fields and attachment_size to trust_requests.

Revision ID: 040
Revises: 039
Create Date: 2026-03-19

"""
from alembic import op
import sqlalchemy as sa

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trust_requests", sa.Column("submitted_host", sa.String(255), nullable=True))
    op.add_column("trust_requests", sa.Column("submitted_path", sa.String(255), nullable=True))
    op.add_column("trust_requests", sa.Column("resolution_method", sa.String(64), nullable=True))
    op.add_column("trust_requests", sa.Column("attachment_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("trust_requests", "attachment_size")
    op.drop_column("trust_requests", "resolution_method")
    op.drop_column("trust_requests", "submitted_path")
    op.drop_column("trust_requests", "submitted_host")
