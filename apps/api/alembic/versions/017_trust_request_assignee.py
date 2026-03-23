"""Trust request assignee (TC-H-B1).

Revision ID: 017
Revises: 016
Create Date: 2026-03-14

"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trust_requests",
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_trust_requests_assignee_id", "trust_requests", ["assignee_id"])


def downgrade() -> None:
    op.drop_index("ix_trust_requests_assignee_id", table_name="trust_requests")
    op.drop_column("trust_requests", "assignee_id")
