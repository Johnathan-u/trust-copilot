"""TC-21-005: versioned question-to-control mapping decisions.

Existing rows were written by both confirm and override with no state, so
they are backfilled as overridden. That keeps suggest treating them as an
override. reviewed_at copies created_at when it is null. History is empty
until a later change snapshots the current version.

Downgrade parks history in tc21005_mapping_hold and parks state, rationale,
version, reviewed_by_user_id and reviewed_at in tc21005_mapping_attr_hold.
The next upgrade restores those held values before any backfill, so the
backfill only fills rows that were never versioned. History rows whose
mapping no longer exists are not copied back.

Revision ID: tc21005_mapping_version
Revises: bug018a_gap_closed_at_reason
"""

from alembic import op
import sqlalchemy as sa

revision = "tc21005_mapping_version"
down_revision = "bug018a_gap_closed_at_reason"
branch_labels = None
depends_on = None

# Frozen. This module must not import the application package.
_CURRENT = "control_mapping_override"
_HISTORY = "tc21005_mapping_history"
_HOLD = "tc21005_mapping_hold"
_ATTR_HOLD = "tc21005_mapping_attr_hold"
_REVIEWER_FK = "fk_control_mapping_override_reviewer"
_REVIEWER_INDEX = "ix_control_mapping_override_reviewed_by_user_id"
_HISTORY_FK = "fk_tc21005_mapping_history_mapping"
_HISTORY_INDEX = "ix_tc21005_mapping_history_mapping_id"
_VERSION_COLUMNS = (
    "state",
    "rationale",
    "version",
    "reviewed_by_user_id",
    "reviewed_at",
)
_HISTORY_COLUMNS = (
    "id, mapping_id, version, workspace_id, question_hash, control_ids, state, "
    "rationale, reviewed_by_user_id, reviewed_at, recorded_at"
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def _fk_names(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {
        fk["name"] for fk in sa.inspect(op.get_bind()).get_foreign_keys(table) if fk.get("name")
    }


def _index_names(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table)}


def _history_table() -> None:
    op.create_table(
        _HISTORY,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapping_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("control_ids", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
    )


def _attr_hold_table() -> None:
    op.create_table(
        _ATTR_HOLD,
        sa.Column("mapping_id", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(length=32), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )


def _hold_table() -> None:
    op.create_table(
        _HOLD,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapping_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("control_ids", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
    )


def upgrade() -> None:
    if _CURRENT not in _tables():
        return
    columns = _columns(_CURRENT)
    if "state" not in columns:
        op.add_column(_CURRENT, sa.Column("state", sa.String(length=32), nullable=True))
    if "rationale" not in columns:
        op.add_column(_CURRENT, sa.Column("rationale", sa.Text(), nullable=True))
    if "version" not in columns:
        op.add_column(_CURRENT, sa.Column("version", sa.Integer(), nullable=True))
    if "reviewed_by_user_id" not in columns:
        op.add_column(_CURRENT, sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True))
    if "reviewed_at" not in columns:
        op.add_column(_CURRENT, sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    if _ATTR_HOLD not in _tables():
        _attr_hold_table()
    # Restore a previous downgrade before backfill, or every row would become overridden v1.
    op.get_bind().execute(
        sa.text(
            f"""
            UPDATE {_CURRENT} AS current
            SET state = held.state,
                rationale = held.rationale,
                version = held.version,
                reviewed_by_user_id = held.reviewed_by_user_id,
                reviewed_at = held.reviewed_at
            FROM {_ATTR_HOLD} AS held
            WHERE current.id = held.mapping_id
            """
        )
    )
    op.get_bind().execute(sa.text(f"DELETE FROM {_ATTR_HOLD}"))
    op.get_bind().execute(
        sa.text(
            f"""
            UPDATE {_CURRENT}
            SET state = 'overridden'
            WHERE state IS NULL
            """
        )
    )
    op.get_bind().execute(
        sa.text(
            f"""
            UPDATE {_CURRENT}
            SET version = 1
            WHERE version IS NULL
            """
        )
    )
    op.get_bind().execute(
        sa.text(f"UPDATE {_CURRENT} SET reviewed_at = created_at WHERE reviewed_at IS NULL")
    )
    op.alter_column(
        _CURRENT,
        "state",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="overridden",
    )
    op.alter_column(
        _CURRENT,
        "version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="1",
    )
    if _REVIEWER_FK not in _fk_names(_CURRENT):
        op.create_foreign_key(
            _REVIEWER_FK,
            _CURRENT,
            "users",
            ["reviewed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if _HOLD not in _tables():
        _hold_table()
    if _HISTORY not in _tables():
        _history_table()
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO {_HISTORY} ({_HISTORY_COLUMNS})
            SELECT {_HISTORY_COLUMNS}
            FROM {_HOLD} AS held
            WHERE NOT EXISTS (
                SELECT 1 FROM {_HISTORY} AS live WHERE live.id = held.id
            )
              AND EXISTS (
                SELECT 1 FROM {_CURRENT} AS mapping WHERE mapping.id = held.mapping_id
              )
            """
        )
    )
    op.get_bind().execute(sa.text(f"DELETE FROM {_HOLD}"))
    op.get_bind().execute(
        sa.text(
            f"""
            DELETE FROM {_HISTORY} AS hist
            WHERE NOT EXISTS (
                SELECT 1 FROM {_CURRENT} AS mapping WHERE mapping.id = hist.mapping_id
            )
            """
        )
    )
    if _HISTORY_FK not in _fk_names(_HISTORY):
        op.create_foreign_key(
            _HISTORY_FK,
            _HISTORY,
            _CURRENT,
            ["mapping_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if _HISTORY_INDEX not in _index_names(_HISTORY):
        op.create_index(_HISTORY_INDEX, _HISTORY, ["mapping_id"])
    if _REVIEWER_INDEX not in _index_names(_CURRENT):
        op.create_index(_REVIEWER_INDEX, _CURRENT, ["reviewed_by_user_id"])
    op.get_bind().execute(
        sa.text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{_HISTORY}', 'id'),
                (SELECT COALESCE(MAX(id), 1) FROM {_HISTORY})
            )
            """
        )
    )


def downgrade() -> None:
    if _HOLD not in _tables():
        _hold_table()
    if _HISTORY in _tables():
        op.get_bind().execute(
            sa.text(
                f"""
                INSERT INTO {_HOLD} ({_HISTORY_COLUMNS})
                SELECT {_HISTORY_COLUMNS}
                FROM {_HISTORY} AS live
                WHERE NOT EXISTS (
                    SELECT 1 FROM {_HOLD} AS held WHERE held.id = live.id
                )
                """
            )
        )
        op.drop_table(_HISTORY)
    if _CURRENT not in _tables():
        return
    columns = _columns(_CURRENT)
    if set(_VERSION_COLUMNS).issubset(columns):
        if _ATTR_HOLD not in _tables():
            _attr_hold_table()
        op.get_bind().execute(
            sa.text(
                f"""
                INSERT INTO {_ATTR_HOLD} (
                    mapping_id, state, rationale, version, reviewed_by_user_id, reviewed_at
                )
                SELECT id, state, rationale, version, reviewed_by_user_id, reviewed_at
                FROM {_CURRENT} AS current
                WHERE NOT EXISTS (
                    SELECT 1 FROM {_ATTR_HOLD} AS held WHERE held.mapping_id = current.id
                )
                """
            )
        )
    if _REVIEWER_INDEX in _index_names(_CURRENT):
        op.drop_index(_REVIEWER_INDEX, table_name=_CURRENT)
    if _REVIEWER_FK in _fk_names(_CURRENT):
        op.drop_constraint(_REVIEWER_FK, _CURRENT, type_="foreignkey")
    for name in (
        "reviewed_at",
        "reviewed_by_user_id",
        "version",
        "rationale",
        "state",
    ):
        if name in columns:
            op.drop_column(_CURRENT, name)
