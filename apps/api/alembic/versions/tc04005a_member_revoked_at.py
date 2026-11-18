"""Workspace-scoped session revocation cutoff (TC-04-005a).

Adds nullable workspace_members.sessions_revoked_at. Null means that workspace
has not revoked existing sessions. A timestamp rejects stored sessions created
at or before it from that workspace only. Existing rows stay null, so current
sessions keep working until an admin revoke.

Downgrade drops the column. Sessions that had been blocked from a workspace
can use it again. That downgrade is lossy for the revocation itself. Re-upgrade
does not restore the dropped timestamps.

The revision id is 26 characters and fits alembic_version.version_num
(varchar(32)). down_revision is the single alembic head on master when this
file is parented. This revision does not import the application package.

Revision ID: tc04005a_member_revoked_at
Revises: tc17005a_share_token
"""

import sqlalchemy as sa
from alembic import op

revision = "tc04005a_member_revoked_at"
down_revision = "tc17005a_share_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_members",
        sa.Column("sessions_revoked_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_members", "sessions_revoked_at")
