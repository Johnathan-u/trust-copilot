"""Trust article slugs unique per workspace (BUG-019).

Public trust pages are /trust/{workspace-slug}. Articles on that page are loaded
for that workspace, so the same article slug may exist in two workspaces.

Replaces the global unique index ix_trust_articles_slug with
uq_trust_articles_workspace_slug on (workspace_id, slug).

Downgrade refuses to restore the global unique index when any slug is shared by
more than one row. It does not delete or rewrite rows.

This module does not import the application package.

Revision ID: bug019_article_slug_ws
Revises: tc21002_control_contract
"""

import sqlalchemy as sa
from alembic import op

revision = "bug019_article_slug_ws"
down_revision = "tc21002_control_contract"
branch_labels = None
depends_on = None

_TABLE = "trust_articles"
_GLOBAL_INDEX = "ix_trust_articles_slug"
_WORKSPACE_UNIQUE = "uq_trust_articles_workspace_slug"


def upgrade() -> None:
    op.drop_index(_GLOBAL_INDEX, table_name=_TABLE)
    op.create_unique_constraint(
        _WORKSPACE_UNIQUE,
        _TABLE,
        ["workspace_id", "slug"],
    )


def downgrade() -> None:
    conn = op.get_bind()
    duplicates = conn.execute(
        sa.text(
            """
            SELECT slug, COUNT(*) AS n
            FROM trust_articles
            GROUP BY slug
            HAVING COUNT(*) > 1
            ORDER BY slug
            """
        )
    ).fetchall()
    if duplicates:
        shown = ", ".join(f"{row.slug} ({row.n})" for row in duplicates[:20])
        extra = "" if len(duplicates) <= 20 else f", and {len(duplicates) - 20} more"
        raise RuntimeError(
            "Cannot restore a global unique slug on trust_articles. "
            f"{len(duplicates)} slug(s) are used by more than one row: {shown}{extra}. "
            "Give those rows distinct slugs before downgrading. This downgrade does not delete rows."
        )
    op.drop_constraint(_WORKSPACE_UNIQUE, _TABLE, type_="unique")
    op.create_index(_GLOBAL_INDEX, _TABLE, ["slug"], unique=True)
