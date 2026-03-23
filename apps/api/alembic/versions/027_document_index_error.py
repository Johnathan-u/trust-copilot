"""Document index_error for failure reason (pre-pilot).

Revision ID: 027
Revises: 026
Create Date: 2025-01-01 00:27:00

"""
from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("index_error", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "index_error")
