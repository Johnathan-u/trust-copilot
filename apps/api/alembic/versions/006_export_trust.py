"""Export records and trust articles (EXP-01, TC-01).

Revision ID: 006
Revises: 005
Create Date: 2025-01-01 00:05:00

"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("questionnaire_id", sa.Integer(), sa.ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), server_default="completed"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_export_records_workspace_id", "export_records", ["workspace_id"])

    op.create_table(
        "trust_articles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("published", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_trust_articles_slug", "trust_articles", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_table("trust_articles")
    op.drop_table("export_records")
