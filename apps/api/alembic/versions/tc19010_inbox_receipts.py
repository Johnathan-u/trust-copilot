"""Personal read receipts for legacy in-app broadcasts (TC-19-010).

Additive: existing notifications and their historical is_read flags are unchanged.
No receipt is backfilled. Parent uniqueness enables strict same-workspace FKs;
legacy duplicate memberships fail closed instead of being silently deduplicated.

Downgrade copies every receipt, including its timestamp, to an archive without
foreign keys before removing the live table and its supporting unique keys.
Re-upgrade restores all archived rows in the migration transaction. Invalid
references fail the upgrade and preserve the archive; no row is skipped or lost.

Revision ID: tc19010_inbox_receipts
Revises: tc10001_job_leases

PROVISIONAL parent only. Coordinator-approved landing slot follows TC-17-004
and TC-23-001; reparent in a separate commit once both have landed.
"""

import sqlalchemy as sa

from alembic import op

revision = "tc19010_inbox_receipts"
down_revision = "tc10001_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_in_app_notifications_workspace_id_id", "in_app_notifications", ["workspace_id", "id"]
    )
    op.create_unique_constraint(
        "uq_workspace_members_workspace_id_user_id",
        "workspace_members",
        ["workspace_id", "user_id"],
    )
    op.create_table(
        "in_app_notification_receipts",
        sa.Column("workspace_id", sa.Integer(), primary_key=True),
        sa.Column("notification_id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "notification_id"],
            ["in_app_notifications.workspace_id", "in_app_notifications.id"],
            name="fk_in_app_receipt_notification_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_members.workspace_id", "workspace_members.user_id"],
            name="fk_in_app_receipt_member_workspace",
            ondelete="CASCADE",
        ),
    )
    # Frozen SQL only: migrations must remain independent of application models.
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('in_app_notification_receipts_archive') IS NOT NULL THEN
                INSERT INTO in_app_notification_receipts
                    (workspace_id, notification_id, user_id, read_at)
                SELECT workspace_id, notification_id, user_id, read_at
                FROM in_app_notification_receipts_archive;
                DROP TABLE in_app_notification_receipts_archive;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # CREATE without IF NOT EXISTS refuses to overwrite a pre-existing archive.
    op.execute("""
        CREATE TABLE in_app_notification_receipts_archive AS
        SELECT workspace_id, notification_id, user_id, read_at
        FROM in_app_notification_receipts
    """)
    op.drop_table("in_app_notification_receipts")
    op.drop_constraint(
        "uq_workspace_members_workspace_id_user_id", "workspace_members", type_="unique"
    )
    op.drop_constraint(
        "uq_in_app_notifications_workspace_id_id", "in_app_notifications", type_="unique"
    )
