"""Create shareable_spaces table.

Revision ID: 063
Revises: 062
"""
from alembic import op
import sqlalchemy as sa

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    if "shareable_spaces" in sa_inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "shareable_spaces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("buyer_company", sa.String(255), nullable=True),
        sa.Column("buyer_email", sa.String(255), nullable=True),
        sa.Column("opportunity_id", sa.String(128), nullable=True),
        sa.Column("access_token", sa.String(255), nullable=True, unique=True, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("article_ids_json", sa.Text(), nullable=True),
        sa.Column("answer_ids_json", sa.Text(), nullable=True),
        sa.Column("document_ids_json", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("shareable_spaces")
