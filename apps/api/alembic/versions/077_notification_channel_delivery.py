"""Notification channel preferences and delivery attempts (TC-19-008).

Revision ID: 077
Revises: 075

Parent is 075, the head of tc/int/TC-19-001. Open PR #23 adds revision 076
with parent 075. Whoever merges second re-parents this down_revision.

"""

from alembic import op
import sqlalchemy as sa


revision = "077"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_log", sa.Column("delivery_state", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "notification_log",
        sa.Column(
            "delivered_to_provider", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "notification_log", sa.Column("provider_mode", sa.String(length=32), nullable=True)
    )
    op.add_column("notification_log", sa.Column("dedupe_key", sa.String(length=512), nullable=True))
    op.add_column("notification_log", sa.Column("attempt_count", sa.Integer(), nullable=True))

    op.create_table(
        "notification_channel_preferences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "workspace_id", "user_id", "channel", "event_type", name="uq_notification_channel_pref"
        ),
    )
    op.create_index(
        "ix_notification_channel_preferences_workspace_id",
        "notification_channel_preferences",
        ["workspace_id"],
    )
    op.create_index(
        "ix_notification_channel_preferences_user_id",
        "notification_channel_preferences",
        ["user_id"],
    )

    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("dedupe_key", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "delivered_to_provider", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("provider_mode", sa.String(length=32), nullable=True),
        sa.Column("template_key", sa.String(length=96), nullable=True),
        sa.Column("rendered_subject", sa.String(length=512), nullable=True),
        sa.Column("rendered_body", sa.Text(), nullable=True),
        sa.Column("destination", sa.String(length=255), nullable=True),
        sa.Column(
            "in_app_notification_id",
            sa.Integer(),
            sa.ForeignKey("in_app_notifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "notification_log_id",
            sa.Integer(),
            sa.ForeignKey("notification_log.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_notification_delivery_attempts_workspace_id",
        "notification_delivery_attempts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_notification_delivery_attempts_event_type",
        "notification_delivery_attempts",
        ["event_type"],
    )
    op.create_index(
        "ix_notification_delivery_attempts_dedupe_key",
        "notification_delivery_attempts",
        ["dedupe_key"],
    )
    op.create_index(
        "ix_notification_delivery_attempts_created_at",
        "notification_delivery_attempts",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_delivery_attempts_created_at", table_name="notification_delivery_attempts"
    )
    op.drop_index(
        "ix_notification_delivery_attempts_dedupe_key", table_name="notification_delivery_attempts"
    )
    op.drop_index(
        "ix_notification_delivery_attempts_event_type", table_name="notification_delivery_attempts"
    )
    op.drop_index(
        "ix_notification_delivery_attempts_workspace_id",
        table_name="notification_delivery_attempts",
    )
    op.drop_table("notification_delivery_attempts")

    op.drop_index(
        "ix_notification_channel_preferences_user_id", table_name="notification_channel_preferences"
    )
    op.drop_index(
        "ix_notification_channel_preferences_workspace_id",
        table_name="notification_channel_preferences",
    )
    op.drop_table("notification_channel_preferences")

    op.drop_column("notification_log", "attempt_count")
    op.drop_column("notification_log", "dedupe_key")
    op.drop_column("notification_log", "provider_mode")
    op.drop_column("notification_log", "delivered_to_provider")
    op.drop_column("notification_log", "delivery_state")
