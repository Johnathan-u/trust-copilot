"""User OAuth accounts table (ENT-201).

Revision ID: 014
Revises: 013
Create Date: 2025-01-01 00:14:00

"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_oauth_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )
    op.create_index("ix_user_oauth_accounts_provider", "user_oauth_accounts", ["provider"])
    op.create_index("ix_user_oauth_accounts_provider_user_id", "user_oauth_accounts", ["provider_user_id"])
    op.create_index("ix_user_oauth_accounts_user_id", "user_oauth_accounts", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_oauth_accounts")
