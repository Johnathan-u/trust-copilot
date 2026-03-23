"""TC-H-B1: Trust request status workflow — canonical statuses, default new.

Revision ID: 022
Revises: 021
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill legacy statuses to canonical values
    op.execute("UPDATE trust_requests SET status = 'new' WHERE status = 'pending'")
    op.execute("UPDATE trust_requests SET status = 'completed' WHERE status IN ('read', 'closed')")
    # Default for new rows
    op.alter_column(
        "trust_requests",
        "status",
        existing_type=sa.String(32),
        server_default="new",
    )


def downgrade() -> None:
    op.alter_column(
        "trust_requests",
        "status",
        existing_type=sa.String(32),
        server_default="pending",
    )
