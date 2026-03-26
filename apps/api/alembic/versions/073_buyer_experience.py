"""Buyer portal, escalations, satisfaction, snapshots (E4-20..E4-24)

Revision ID: 073
Revises: 072
"""
from alembic import op
import sqlalchemy as sa

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buyer_portals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portal_token", sa.String(96), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("frameworks_filter_json", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "buyer_portal_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portal_id", sa.Integer(), sa.ForeignKey("buyer_portals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "buyer_escalations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portal_id", sa.Integer(), sa.ForeignKey("buyer_portals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("buyer_email", sa.String(255), nullable=False),
        sa.Column("escalation_type", sa.String(64), nullable=False),
        sa.Column("question_snippet", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("answer_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("seller_notes", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "buyer_satisfaction_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portal_id", sa.Integer(), sa.ForeignKey("buyer_portals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("questionnaire_id", sa.Integer(), nullable=True),
        sa.Column("accepted_without_edits", sa.Boolean(), nullable=True),
        sa.Column("follow_up_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("cycle_hours", sa.Float(), nullable=True),
        sa.Column("deal_closed", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("extra_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "buyer_change_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("portal_id", sa.Integer(), sa.ForeignKey("buyer_portals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("frameworks_json", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("buyer_change_subscriptions")
    op.drop_table("buyer_satisfaction_signals")
    op.drop_table("buyer_escalations")
    op.drop_table("buyer_portal_snapshots")
    op.drop_table("buyer_portals")
