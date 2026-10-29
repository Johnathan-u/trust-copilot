"""TC-21-003: one link per control and evidence item.

The control row already belongs to one workspace, so (control_id, evidence_id)
is the scoped pair. Null pairs are not possible. If two links already share
that pair, the oldest row stays. Later rows are copied here and removed so
downgrade can put them back. Evidence items are not deleted.

Revision ID: tc21003_evidence_link_uniq
Revises: tc21002a_canonical_uniq
"""

from alembic import op
import sqlalchemy as sa

revision = "tc21003_evidence_link_uniq"
down_revision = "tc21002a_canonical_uniq"
branch_labels = None
depends_on = None

# Frozen. This module must not import the application package.
_LINKS = "control_evidence_links"
_HOLD = "tc21003_link_hold"
_INDEX = "uq_control_evidence_links_pair"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names() -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(_LINKS)}


def upgrade() -> None:
    if _HOLD not in _tables():
        op.create_table(
            _HOLD,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("link_id", sa.Integer(), nullable=False),
            sa.Column("control_id", sa.Integer(), nullable=False),
            sa.Column("evidence_id", sa.Integer(), nullable=False),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("verified", sa.Boolean(), nullable=False),
            sa.Column("last_verified_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("link_id", name="uq_tc21003_link_hold_link"),
        )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"""
            INSERT INTO {_HOLD} (
                link_id, control_id, evidence_id, confidence_score, verified,
                last_verified_at, created_at
            )
            SELECT c.id, c.control_id, c.evidence_id, c.confidence_score, c.verified,
                   c.last_verified_at, c.created_at
            FROM {_LINKS} AS c
            WHERE c.id <> (
                SELECT MIN(older.id)
                FROM {_LINKS} AS older
                WHERE older.control_id = c.control_id
                  AND older.evidence_id = c.evidence_id
            )
              AND NOT EXISTS (
                SELECT 1 FROM {_HOLD} AS held WHERE held.link_id = c.id
              )
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            DELETE FROM {_LINKS} AS c
            WHERE EXISTS (
                SELECT 1 FROM {_HOLD} AS held WHERE held.link_id = c.id
            )
            """
        )
    )
    if _INDEX not in _index_names():
        op.create_index(
            _INDEX,
            _LINKS,
            ["control_id", "evidence_id"],
            unique=True,
        )


def downgrade() -> None:
    if _INDEX in _index_names():
        op.drop_index(_INDEX, table_name=_LINKS)
    if _HOLD in _tables():
        op.get_bind().execute(
            sa.text(
                f"""
                INSERT INTO {_LINKS} (
                    id, control_id, evidence_id, confidence_score, verified,
                    last_verified_at, created_at
                )
                SELECT held.link_id, held.control_id, held.evidence_id,
                       held.confidence_score, held.verified, held.last_verified_at,
                       held.created_at
                FROM {_HOLD} AS held
                WHERE NOT EXISTS (
                    SELECT 1 FROM {_LINKS} AS live WHERE live.id = held.link_id
                )
                """
            )
        )
        op.drop_table(_HOLD)
