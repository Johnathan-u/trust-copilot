"""Hash shareable-space tokens at rest (TC-17-005a).

Adds nullable token_hash and backfills it with the SHA-256 hex digest of each
stored access_token (UTF-8), then sets access_token to null. expires_at and
is_active are not modified. A null access_token stays null and gets no hash.

Downgrade drops token_hash. It cannot rebuild the raw tokens, so access_token
stays null and previously issued links stop working on the old code. That is
lossy. Re-upgrade does not invent replacements.

down_revision is the single alembic head on master when this file is parented.
Re-parent by changing that one assignment. This revision does not import the
application package. The digest matches shareable_space_service._digest.

Revision ID: tc17005a_share_token
Revises: question_cell_mapping
"""

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "tc17005a_share_token"
down_revision = "question_cell_mapping"
branch_labels = None
depends_on = None

_INDEX = "ix_shareable_spaces_token_hash"


def upgrade() -> None:
    op.add_column(
        "shareable_spaces",
        sa.Column("token_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(_INDEX, "shareable_spaces", ["token_hash"], unique=True)
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, access_token FROM shareable_spaces WHERE access_token IS NOT NULL")
    ).fetchall()
    for row in rows:
        raw = row.access_token
        if not raw:
            bind.execute(
                sa.text("UPDATE shareable_spaces SET access_token = NULL WHERE id = :id"),
                {"id": row.id},
            )
            continue
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        bind.execute(
            sa.text(
                "UPDATE shareable_spaces SET token_hash = :digest, access_token = NULL "
                "WHERE id = :id AND access_token = :raw"
            ),
            {"digest": digest, "id": row.id, "raw": raw},
        )


def downgrade() -> None:
    # Lossy: the raw tokens were discarded in upgrade and cannot be restored.
    op.drop_index(_INDEX, table_name="shareable_spaces")
    op.drop_column("shareable_spaces", "token_hash")
