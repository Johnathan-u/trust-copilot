"""Create source_registry table.

Revision ID: 056
Revises: 055
"""
from alembic import op
import sqlalchemy as sa

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    if "source_registry" in sa_inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "source_registry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_type", sa.String(64), nullable=False, index=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("auth_method", sa.String(64), nullable=False, server_default="none"),
        sa.Column("sync_cadence", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("object_types", sa.Text(), nullable=True),
        sa.Column("failure_modes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="available"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("source_registry")
