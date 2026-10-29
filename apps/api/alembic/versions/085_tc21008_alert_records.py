"""Persist compliance alert condition and lifecycle.

One active row per workspace, condition, and source. Downgrade parks the rows
and upgrade puts them back.

Revision ID: tc21008_alert_records
Revises: tc02001a_parent_ws_move
"""

import sqlalchemy as sa
from alembic import op

revision = "tc21008_alert_records"
down_revision = "tc02001a_parent_ws_move"
branch_labels = None
depends_on = None

_HOLD = "tc21008_alert_hold"
_TABLE = "compliance_alerts"
_INDEX = "uq_compliance_alerts_one_active"
_COLUMNS = (
    "id",
    "workspace_id",
    "condition",
    "source_ref",
    "source_revision",
    "control_id",
    "control_revision",
    "status",
    "severity",
    "title",
    "description",
    "metric",
    "reason",
    "snoozed_until",
    "resolved_at",
    "actor_user_id",
    "created_at",
    "updated_at",
)


def _names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_list() -> str:
    return ", ".join(_COLUMNS)


def _create_table(name: str, primary: bool) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), primary_key=primary, autoincrement=primary),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=160), nullable=False),
        sa.Column("source_revision", sa.String(length=64), nullable=True),
        sa.Column("control_id", sa.Integer(), nullable=True),
        sa.Column("control_revision", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metric", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    names = _names()
    if _TABLE not in names:
        _create_table(_TABLE, primary=True)
        op.create_index(
            _INDEX,
            _TABLE,
            ["workspace_id", "condition", "source_ref"],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        )
        op.create_foreign_key(
            "fk_compliance_alerts_workspace",
            _TABLE,
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if _HOLD in _names():
        op.execute(
            f"INSERT INTO {_TABLE} ({_column_list()}) "
            f"SELECT {_column_list()} FROM {_HOLD} "
            f"ON CONFLICT (id) DO NOTHING"
        )
        op.execute(f"DELETE FROM {_HOLD}")
        op.execute(
            "SELECT setval(pg_get_serial_sequence('compliance_alerts', 'id'), "
            "GREATEST((SELECT COALESCE(MAX(id), 1) FROM compliance_alerts), 1))"
        )


def downgrade() -> None:
    names = _names()
    if _TABLE not in names:
        return
    if _HOLD not in names:
        _create_table(_HOLD, primary=True)
    op.execute(
        f"INSERT INTO {_HOLD} ({_column_list()}) "
        f"SELECT {_column_list()} FROM {_TABLE} "
        f"ON CONFLICT (id) DO NOTHING"
    )
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f"DROP TABLE {_TABLE}")
