"""remediation playbooks and tickets

Revision ID: 070
Revises: 069
"""
from alembic import op
import sqlalchemy as sa

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "remediation_playbooks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("control_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps_json", sa.Text(), nullable=True),
        sa.Column("evidence_needed_json", sa.Text(), nullable=True),
        sa.Column("default_assignee_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("severity", sa.String(32), server_default="medium"),
        sa.Column("sla_hours", sa.Integer(), nullable=True, server_default="72"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "remediation_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("playbook_id", sa.Integer(), sa.ForeignKey("remediation_playbooks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("control_id", sa.Integer(), sa.ForeignKey("workspace_controls.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("assignee_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deadline", sa.DateTime(), nullable=True),
        sa.Column("affected_deal_ids_json", sa.Text(), nullable=True),
        sa.Column("evidence_needed_json", sa.Text(), nullable=True),
        sa.Column("external_ticket_id", sa.String(255), nullable=True),
        sa.Column("external_ticket_url", sa.String(512), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("remediation_tickets")
    op.drop_table("remediation_playbooks")
