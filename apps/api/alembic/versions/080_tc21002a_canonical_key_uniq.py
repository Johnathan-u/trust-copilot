"""TC-21-002a: one canonical key per workspace.

Partial unique indexes. Null keys stay allowed, so rows written before
TC-21-002 are not backfilled. If a workspace already has two rows with the
same non-null key, the oldest row keeps it. Later rows keep their status,
name, and evidence, and their key is stored here so downgrade can put it back.

Revision ID: tc21002a_canonical_uniq
Revises: bug019_article_slug_ws
"""

from alembic import op
import sqlalchemy as sa

revision = "tc21002a_canonical_uniq"
down_revision = "bug019_article_slug_ws"
branch_labels = None
depends_on = None

# Frozen. This module must not import the application package.
_HOLD = "tc21002a_key_hold"
_CONTROLS = "controls"
_WORKSPACE = "workspace_controls"
_UQ_CONTROLS = "uq_controls_ws_canonical_key"
_UQ_WORKSPACE = "uq_ws_controls_ws_canonical_key"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table)}


def _clear_duplicate_keys(table: str) -> None:
    """Keep the oldest non-null key. Remember every key this step clears."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"""
            INSERT INTO {_HOLD} (source_table, row_id, canonical_key)
            SELECT :table, c.id, c.canonical_key
            FROM {table} AS c
            WHERE c.canonical_key IS NOT NULL
              AND c.id <> (
                    SELECT MIN(older.id)
                    FROM {table} AS older
                    WHERE older.workspace_id = c.workspace_id
                      AND older.canonical_key = c.canonical_key
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM {_HOLD} AS held
                    WHERE held.source_table = :table AND held.row_id = c.id
                  )
            """
        ),
        {"table": table},
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE {table} AS c
            SET canonical_key = NULL
            WHERE EXISTS (
                SELECT 1 FROM {_HOLD} AS held
                WHERE held.source_table = :table
                  AND held.row_id = c.id
                  AND held.canonical_key = c.canonical_key
            )
            """
        ),
        {"table": table},
    )


def _restore_cleared_keys(table: str) -> None:
    op.get_bind().execute(
        sa.text(
            f"""
            UPDATE {table} AS c
            SET canonical_key = held.canonical_key
            FROM {_HOLD} AS held
            WHERE held.source_table = :table
              AND held.row_id = c.id
              AND c.canonical_key IS NULL
            """
        ),
        {"table": table},
    )


def upgrade() -> None:
    if _HOLD not in _tables():
        op.create_table(
            _HOLD,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_table", sa.String(64), nullable=False),
            sa.Column("row_id", sa.Integer(), nullable=False),
            sa.Column("canonical_key", sa.String(160), nullable=False),
            sa.UniqueConstraint("source_table", "row_id", name="uq_tc21002a_key_hold_row"),
        )
    _clear_duplicate_keys(_CONTROLS)
    _clear_duplicate_keys(_WORKSPACE)
    if _UQ_CONTROLS not in _index_names(_CONTROLS):
        op.create_index(
            _UQ_CONTROLS,
            _CONTROLS,
            ["workspace_id", "canonical_key"],
            unique=True,
            postgresql_where=sa.text("canonical_key IS NOT NULL"),
        )
    if _UQ_WORKSPACE not in _index_names(_WORKSPACE):
        op.create_index(
            _UQ_WORKSPACE,
            _WORKSPACE,
            ["workspace_id", "canonical_key"],
            unique=True,
            postgresql_where=sa.text("canonical_key IS NOT NULL"),
        )


def downgrade() -> None:
    if _UQ_WORKSPACE in _index_names(_WORKSPACE):
        op.drop_index(_UQ_WORKSPACE, table_name=_WORKSPACE)
    if _UQ_CONTROLS in _index_names(_CONTROLS):
        op.drop_index(_UQ_CONTROLS, table_name=_CONTROLS)
    if _HOLD in _tables():
        _restore_cleared_keys(_CONTROLS)
        _restore_cleared_keys(_WORKSPACE)
        op.drop_table(_HOLD)
