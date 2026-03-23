"""Add 14 missing tables (Phase A-F, dashboard, quotas) and 3 missing columns.

These tables/columns were created via manual DDL on the dev database but never
captured as Alembic migrations, causing trustcopilot_test to be incomplete
when built from migration history alone.

Revision ID: 035
Revises: 034
"""

from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Phase B: custom roles ---
    op.create_table(
        "custom_roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("can_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_review", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("can_export", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_custom_roles_workspace_id", "custom_roles", ["workspace_id"])

    # --- Phase C: notification policies, log, unsubscribes ---
    op.create_table(
        "notification_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("recipient_type", sa.String(32), nullable=False, server_default=sa.text("'admins'")),
        sa.Column("recipient_value", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notification_policies_workspace_id", "notification_policies", ["workspace_id"])

    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default=sa.text("'email'")),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'sent'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notification_log_workspace_id", "notification_log", ["workspace_id"])
    op.create_index("ix_notification_log_event_type", "notification_log", ["event_type"])
    op.create_index("ix_notification_log_created_at", "notification_log", ["created_at"])

    op.create_table(
        "notification_unsubscribes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    # --- Phase D: Slack integration ---
    op.create_table(
        "slack_integrations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.String(64), nullable=False),
        sa.Column("channel_name", sa.String(255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("event_types", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_slack_integrations_workspace_id", "slack_integrations", ["workspace_id"], unique=True)

    # --- Phase E: Slack ingest ---
    op.create_table(
        "slack_ingest_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slack_integration_id", sa.Integer(), sa.ForeignKey("slack_integrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.String(64), nullable=False),
        sa.Column("channel_name", sa.String(255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_slack_ingest_channels_workspace_id", "slack_ingest_channels", ["workspace_id"])

    op.create_table(
        "slack_control_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_id", sa.Integer(), sa.ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_slack_control_suggestions_workspace_id", "slack_control_suggestions", ["workspace_id"])
    op.create_index("ix_slack_control_suggestions_evidence_id", "slack_control_suggestions", ["evidence_id"])

    # --- In-app notifications ---
    op.create_table(
        "in_app_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("category", sa.String(32), nullable=False, server_default=sa.text("'info'")),
        sa.Column("link", sa.String(512), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("admin_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_in_app_notifications_workspace_id", "in_app_notifications", ["workspace_id"])
    op.create_index("ix_in_app_notifications_user_id", "in_app_notifications", ["user_id"])
    op.create_index("ix_in_app_notifications_created_at", "in_app_notifications", ["created_at"])

    # --- Phase F: Gmail integration ---
    op.create_table(
        "gmail_integrations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("email_address", sa.String(255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_gmail_integrations_workspace_id", "gmail_integrations", ["workspace_id"], unique=True)

    op.create_table(
        "gmail_ingest_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gmail_integration_id", sa.Integer(), sa.ForeignKey("gmail_integrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label_id", sa.String(255), nullable=False),
        sa.Column("label_name", sa.String(255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_gmail_ingest_labels_workspace_id", "gmail_ingest_labels", ["workspace_id"])

    op.create_table(
        "gmail_control_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_id", sa.Integer(), sa.ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_gmail_control_suggestions_workspace_id", "gmail_control_suggestions", ["workspace_id"])
    op.create_index("ix_gmail_control_suggestions_evidence_id", "gmail_control_suggestions", ["evidence_id"])

    # --- Dashboard cards ---
    op.create_table(
        "dashboard_cards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(32), nullable=False, server_default=sa.text("'document'")),
        sa.Column("target_route", sa.String(256), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("visibility_scope", sa.String(16), nullable=False, server_default=sa.text("'all'")),
        sa.Column("size", sa.String(16), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_dashboard_cards_workspace_id", "dashboard_cards", ["workspace_id"])

    # --- Workspace quotas and usage ---
    op.create_table(
        "workspace_quotas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("max_documents", sa.Integer(), nullable=False, server_default=sa.text("500")),
        sa.Column("max_questionnaires", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("max_jobs_per_hour", sa.Integer(), nullable=False, server_default=sa.text("50")),
        sa.Column("max_exports_per_hour", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("max_slack_ingests_per_hour", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("max_gmail_ingests_per_hour", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("max_ai_jobs_per_hour", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("max_notifications_per_hour", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workspace_quotas_workspace_id", "workspace_quotas", ["workspace_id"], unique=True)

    op.create_table(
        "workspace_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_workspace_usage_workspace_id", "workspace_usage", ["workspace_id"])

    # --- Missing columns on existing tables ---

    # Phase A: workspace_members.suspended
    op.add_column(
        "workspace_members",
        sa.Column("suspended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # Automate-everything flag
    op.add_column(
        "workspaces",
        sa.Column("ai_automate_everything", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # Evidence source metadata
    op.add_column(
        "evidence_items",
        sa.Column("source_metadata", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evidence_items", "source_metadata")
    op.drop_column("workspaces", "ai_automate_everything")
    op.drop_column("workspace_members", "suspended")
    op.drop_table("workspace_usage")
    op.drop_table("workspace_quotas")
    op.drop_table("dashboard_cards")
    op.drop_table("gmail_control_suggestions")
    op.drop_table("gmail_ingest_labels")
    op.drop_table("gmail_integrations")
    op.drop_table("in_app_notifications")
    op.drop_table("slack_control_suggestions")
    op.drop_table("slack_ingest_channels")
    op.drop_table("slack_integrations")
    op.drop_table("notification_unsubscribes")
    op.drop_table("notification_log")
    op.drop_table("notification_policies")
    op.drop_table("custom_roles")
