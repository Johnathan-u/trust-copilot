"""Record whether a session completed an MFA challenge (TC-05-001c).

SCHEMA CHANGE. Review this migration before it is applied.

``user_sessions.mfa_satisfied`` is false for every existing row. A session
created before this column cannot switch into a workspace that requires MFA
until the user completes a fresh challenge. Downgrade drops the column.
Upgrade again sets every row false; a previous true value is not restored.
That is fail closed: the next switch into an MFA workspace asks for a challenge.

The revision id fits alembic_version.version_num (varchar(32)). down_revision
is the single alembic head on master when this file is parented. This revision
does not import the application package.

Revision ID: tc05001c_mfa_satisfied
Revises: tc17001_article_versions
"""

import sqlalchemy as sa
from alembic import op

revision = "tc05001c_mfa_satisfied"
down_revision = "tc17001_article_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_sessions",
        sa.Column(
            "mfa_satisfied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_sessions", "mfa_satisfied")
