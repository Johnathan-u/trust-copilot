"""API keys table for machine auth.

Revision ID: 025
Revises: 024
Create Date: 2025-01-01 00:25:00

"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="editor"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_workspace_id", "api_keys", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("api_keys")
