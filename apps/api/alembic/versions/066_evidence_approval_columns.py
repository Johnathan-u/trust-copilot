"""evidence item approval columns

Revision ID: 066
Revises: 065
"""
from alembic import op
import sqlalchemy as sa

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence_items", sa.Column("approval_status", sa.String(32), nullable=True, server_default="pending"))
    op.add_column("evidence_items", sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("evidence_items", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("evidence_items", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence_items", "rejection_reason")
    op.drop_column("evidence_items", "approved_at")
    op.drop_column("evidence_items", "approved_by_user_id")
    op.drop_column("evidence_items", "approval_status")
