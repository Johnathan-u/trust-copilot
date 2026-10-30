"""Record which session key id signed a stored session (TC-07-002).

Nullable. Existing rows stay null and keep working with unprefixed cookies.
Downgrade archives non-null key metadata before dropping the column. Re-upgrade
restores only an exact session identity and retains unmatched archive entries.

Revision ID: tc07002_session_key_id
Revises: tc19010_inbox_receipts
"""

import sqlalchemy as sa
from alembic import op

revision = "tc07002_session_key_id"
down_revision = "tc19010_inbox_receipts"
branch_labels = None
depends_on = None

ARCHIVE = "tc07002_session_key_archive"
# Frozen identity columns from the parent schema. A reused row id alone is not a session.
IDENTITY_MATCH = """
    s.id = a.id AND s.user_id = a.user_id AND s.session_id = a.session_id
    AND s.created_at IS NOT DISTINCT FROM a.created_at
"""


def _ensure_archive() -> None:
    # No foreign keys: logout/deletion must neither resurrect a session nor lose its archive.
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {ARCHIVE} (
            id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            session_id VARCHAR(64) NOT NULL, created_at TIMESTAMP,
            signing_key_id VARCHAR(64) NOT NULL
        )
    """)


def upgrade() -> None:
    op.add_column(
        "user_sessions",
        sa.Column("signing_key_id", sa.String(length=64), nullable=True),
    )
    _ensure_archive()
    op.execute(f"""
        UPDATE user_sessions AS s
        SET signing_key_id = (
            SELECT a.signing_key_id FROM {ARCHIVE} AS a WHERE {IDENTITY_MATCH}
        )
        WHERE EXISTS (SELECT 1 FROM {ARCHIVE} AS a WHERE {IDENTITY_MATCH})
    """)
    # Consume only successfully restored values. Changed/deleted identities remain archived.
    op.execute(f"""
        DELETE FROM {ARCHIVE} AS a
        WHERE EXISTS (
            SELECT 1 FROM user_sessions AS s
            WHERE {IDENTITY_MATCH} AND s.signing_key_id = a.signing_key_id
        )
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Freeze session writes until the snapshot and column removal commit together.
        op.execute("LOCK TABLE user_sessions IN ACCESS EXCLUSIVE MODE")
    _ensure_archive()
    # Refresh the same live identity without overwriting an unmatched archived session.
    op.execute(f"""
        DELETE FROM {ARCHIVE} AS a
        WHERE EXISTS (
            SELECT 1 FROM user_sessions AS s
            WHERE {IDENTITY_MATCH} AND s.signing_key_id IS NOT NULL
        )
    """)
    op.execute(f"""
        INSERT INTO {ARCHIVE} (id, user_id, session_id, created_at, signing_key_id)
        SELECT id, user_id, session_id, created_at, signing_key_id
        FROM user_sessions WHERE signing_key_id IS NOT NULL
    """)
    op.drop_column("user_sessions", "signing_key_id")
