"""Phase 5: Workspace staleness config, compliance webhook outbox."""

from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("evidence_stale_verified_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column("evidence_stale_unverified_days", sa.Integer(), nullable=True),
    )
    op.create_table(
        "compliance_webhook_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("compliance_webhook_outbox")
    op.drop_column("workspaces", "evidence_stale_unverified_days")
    op.drop_column("workspaces", "evidence_stale_verified_days")
