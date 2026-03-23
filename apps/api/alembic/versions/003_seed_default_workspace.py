"""Seed default workspace for dev.

Revision ID: 003
Revises: 002
Create Date: 2025-01-01 00:02:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        INSERT INTO workspaces (id, name, slug, created_at, updated_at)
        SELECT 1, 'Default', 'default', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM workspaces WHERE id = 1)
    """))


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM workspaces WHERE id = 1"))
