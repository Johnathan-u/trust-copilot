"""Workspace AI settings (model + temperature).

Revision ID: 016
Revises: 015
Create Date: 2026-03-14 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("ai_completion_model", sa.String(length=255), nullable=True))
    op.add_column("workspaces", sa.Column("ai_temperature", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "ai_temperature")
    op.drop_column("workspaces", "ai_completion_model")

