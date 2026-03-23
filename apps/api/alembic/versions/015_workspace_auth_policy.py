"""Workspace auth policy columns (ENT-202).

Revision ID: 015
Revises: 014
Create Date: 2025-01-01 00:15:00

"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("mfa_required", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("workspaces", sa.Column("session_max_age_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "session_max_age_seconds")
    op.drop_column("workspaces", "mfa_required")
