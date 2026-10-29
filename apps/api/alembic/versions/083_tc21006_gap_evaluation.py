"""TC-21-006: explainable control-scan columns on evidence_gaps.

Questionnaire gaps leave these columns null. Downgrade parks any non-null
values in tc21006_gap_eval_hold and upgrade restores them before nothing else
writes a default. This module does not import the application package.

Revision ID: tc21006_gap_evaluation
Revises: bug018a_gap_closed_at_reason
"""

from alembic import op
import sqlalchemy as sa

revision = "tc21006_gap_evaluation"
down_revision = "bug018a_gap_closed_at_reason"
branch_labels = None
depends_on = None

_TABLE = "evidence_gaps"
_HOLD = "tc21006_gap_eval_hold"
_COLUMNS = (
    "control_id",
    "evaluation_state",
    "rule_code",
    "evidence_refs",
    "next_action",
    "owner_user_id",
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def _hold_table() -> None:
    op.create_table(
        _HOLD,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("control_id", sa.Integer(), nullable=True),
        sa.Column("evaluation_state", sa.String(length=16), nullable=True),
        sa.Column("rule_code", sa.String(length=64), nullable=True),
        sa.Column("evidence_refs", sa.Text(), nullable=True),
        sa.Column("next_action", sa.String(length=64), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
    )


def upgrade() -> None:
    if _TABLE not in _tables():
        return
    columns = _columns(_TABLE)
    specs = (
        ("control_id", sa.Integer()),
        ("evaluation_state", sa.String(length=16)),
        ("rule_code", sa.String(length=64)),
        ("evidence_refs", sa.Text()),
        ("next_action", sa.String(length=64)),
        ("owner_user_id", sa.Integer()),
    )
    for name, type_ in specs:
        if name not in columns:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))
    if _HOLD not in _tables():
        _hold_table()
    op.get_bind().execute(
        sa.text(
            f"""
            UPDATE {_TABLE} AS gap
            SET control_id = held.control_id,
                evaluation_state = held.evaluation_state,
                rule_code = held.rule_code,
                evidence_refs = held.evidence_refs,
                next_action = held.next_action,
                owner_user_id = held.owner_user_id
            FROM {_HOLD} AS held
            WHERE gap.id = held.id
            """
        )
    )
    op.get_bind().execute(sa.text(f"DELETE FROM {_HOLD}"))


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    columns = _columns(_TABLE)
    if set(_COLUMNS).issubset(columns):
        if _HOLD not in _tables():
            _hold_table()
        op.get_bind().execute(
            sa.text(
                f"""
                INSERT INTO {_HOLD} (
                    id, control_id, evaluation_state, rule_code, evidence_refs,
                    next_action, owner_user_id
                )
                SELECT id, control_id, evaluation_state, rule_code, evidence_refs,
                       next_action, owner_user_id
                FROM {_TABLE} AS gap
                WHERE (
                    gap.control_id IS NOT NULL
                    OR gap.evaluation_state IS NOT NULL
                    OR gap.rule_code IS NOT NULL
                    OR gap.evidence_refs IS NOT NULL
                    OR gap.next_action IS NOT NULL
                    OR gap.owner_user_id IS NOT NULL
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM {_HOLD} AS held WHERE held.id = gap.id
                  )
                """
            )
        )
    for name in reversed(_COLUMNS):
        if name in columns:
            op.drop_column(_TABLE, name)
