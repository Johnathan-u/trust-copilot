"""Create nda_access_requests table.

Revision ID: 062
Revises: 061
"""
from alembic import op
import sqlalchemy as sa

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    if "nda_access_requests" in sa_inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "nda_access_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("requester_name", sa.String(255), nullable=False),
        sa.Column("requester_email", sa.String(255), nullable=False),
        sa.Column("requester_company", sa.String(255), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("nda_accepted", sa.Boolean(), default=False, nullable=False),
        sa.Column("nda_accepted_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(32), default="pending", nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("access_token", sa.String(255), nullable=True, unique=True, index=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("nda_access_requests")
