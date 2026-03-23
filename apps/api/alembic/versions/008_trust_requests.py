"""Trust requests table (TC-04).

Revision ID: 008
Revises: 007
Create Date: 2025-01-01 00:08:00

"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trust_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requester_email", sa.String(255), nullable=False),
        sa.Column("requester_name", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_trust_requests_workspace_id", "trust_requests", ["workspace_id"])
    op.create_index("ix_trust_requests_status", "trust_requests", ["status"])


def downgrade() -> None:
    op.drop_table("trust_requests")
