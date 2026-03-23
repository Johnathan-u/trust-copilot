"""Phase 6: Webhook outbox delivery fields, workspace webhook URL."""

from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "compliance_webhook_outbox",
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "compliance_webhook_outbox",
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
    )
    op.add_column(
        "compliance_webhook_outbox",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "compliance_webhook_outbox",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "workspaces",
        sa.Column("compliance_webhook_url", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "compliance_webhook_url")
    op.drop_column("compliance_webhook_outbox", "attempt_count")
    op.drop_column("compliance_webhook_outbox", "last_error")
    op.drop_column("compliance_webhook_outbox", "status")
    op.drop_column("compliance_webhook_outbox", "delivered_at")
