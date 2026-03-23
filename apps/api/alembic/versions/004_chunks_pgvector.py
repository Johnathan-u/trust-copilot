"""Chunks table with pgvector for semantic search (DOC-08, RET-01).

Revision ID: 004
Revises: 003
Create Date: 2025-01-01 00:03:00

"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_", sa.JSON(), nullable=True),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_chunks_workspace_id", "chunks", ["workspace_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # Note: Add ivfflat/hnsw index after table has data for better recall


def downgrade() -> None:
    op.drop_table("chunks")
