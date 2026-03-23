"""Answer pipeline caches and corpus version.

Revision ID: 028
Revises: 027
Create Date: 2025-01-01 00:28:00

"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_corpus_versions",
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_token", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "answer_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cache_key", sa.String(128), nullable=False),
        sa.Column("response_style", sa.String(32), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(128), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("citations", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_answer_cache_workspace_key", "answer_cache", ["workspace_id", "cache_key"], unique=True)
    op.create_index("ix_answer_cache_cache_key", "answer_cache", ["cache_key"])

    op.create_table(
        "retrieval_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cache_key", sa.String(128), nullable=False),
        sa.Column("corpus_version", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_retrieval_cache_workspace_key", "retrieval_cache", ["workspace_id", "cache_key"], unique=True)
    op.create_index("ix_retrieval_cache_workspace_id", "retrieval_cache", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_cache_workspace_id", table_name="retrieval_cache")
    op.drop_index("ix_retrieval_cache_workspace_key", table_name="retrieval_cache")
    op.drop_table("retrieval_cache")
    op.drop_index("ix_answer_cache_cache_key", table_name="answer_cache")
    op.drop_index("ix_answer_cache_workspace_key", table_name="answer_cache")
    op.drop_table("answer_cache")
    op.drop_table("workspace_corpus_versions")
