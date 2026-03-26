"""Create control_state_snapshots table.

Revision ID: 060
Revises: 059
"""
from alembic import op
import sqlalchemy as sa

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    if "control_state_snapshots" in sa_inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "control_state_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("control_id", sa.Integer(), sa.ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("evaluated_by", sa.String(64), nullable=False, server_default="system"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("control_state_snapshots")
