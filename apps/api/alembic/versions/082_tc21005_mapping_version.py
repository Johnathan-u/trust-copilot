"""TC-21-005: versioned question-to-control mapping decisions.

Existing rows were written by both confirm and override with no state, so
they are backfilled as overridden. That keeps suggest treating them as an
override. reviewed_at copies created_at when it is null. History is empty
until a later change snapshots the current version.

Downgrade parks history in tc21005_mapping_hold and drops the new columns.
The next upgrade copies that hold back, including ids, then empties the hold.

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
_REVIEWER_FK = "fk_control_mapping_override_reviewer"
_HISTORY_COLUMNS = (
    "id, mapping_id, version, workspace_id, question_hash, control_ids, state, "
    "rationale, reviewed_by_user_id, reviewed_at, recorded_at"
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def _fk_names(table: str) -> set[str]:
    return {
        fk["name"] for fk in sa.inspect(op.get_bind()).get_foreign_keys(table) if fk.get("name")
    }


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
        op.add_column(
            _CURRENT,
            sa.Column("state", sa.String(length=32), nullable=False, server_default="overridden"),
        )
    if "rationale" not in columns:
        op.add_column(_CURRENT, sa.Column("rationale", sa.Text(), nullable=True))
    if "version" not in columns:
        op.add_column(
            _CURRENT,
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )
    if "reviewed_by_user_id" not in columns:
        op.add_column(_CURRENT, sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True))
    if "reviewed_at" not in columns:
        op.add_column(_CURRENT, sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    if _REVIEWER_FK not in _fk_names(_CURRENT):
        op.create_foreign_key(
            _REVIEWER_FK,
            _CURRENT,
            "users",
            ["reviewed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.get_bind().execute(
        sa.text(f"UPDATE {_CURRENT} SET reviewed_at = created_at WHERE reviewed_at IS NULL")
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
            """
        )
    )
    op.get_bind().execute(sa.text(f"DELETE FROM {_HOLD}"))
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
    if _REVIEWER_FK in _fk_names(_CURRENT):
        op.drop_constraint(_REVIEWER_FK, _CURRENT, type_="foreignkey")
    columns = _columns(_CURRENT)
    for name in (
        "reviewed_at",
        "reviewed_by_user_id",
        "version",
        "rationale",
        "state",
    ):
        if name in columns:
            op.drop_column(_CURRENT, name)
