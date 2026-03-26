"""remediation evidence linkage, audit log, automation opt-in

Revision ID: 071
Revises: 070
"""
from alembic import op
import sqlalchemy as sa

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("remediation_tickets", sa.Column("linked_evidence_ids_json", sa.Text(), nullable=True))
    op.create_table(
        "remediation_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("remediation_tickets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "remediation_automation_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("automation_key", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_remediation_automation_workspace_key",
        "remediation_automation_settings",
        ["workspace_id", "automation_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_remediation_automation_workspace_key", table_name="remediation_automation_settings")
    op.drop_table("remediation_automation_settings")
    op.drop_table("remediation_audit_events")
    op.drop_column("remediation_tickets", "linked_evidence_ids_json")
