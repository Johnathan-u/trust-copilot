"""Worker heartbeat table for /workerz visibility.

Revision ID: 026
Revises: 025
Create Date: 2025-01-01 00:26:00

"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeat",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_seen_utc", sa.DateTime(), nullable=False),
    )
    op.execute("INSERT INTO worker_heartbeat (id, last_seen_utc) VALUES (1, NOW())")


def downgrade() -> None:
    op.drop_table("worker_heartbeat")
