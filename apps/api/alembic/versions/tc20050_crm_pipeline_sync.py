"""CRM pipeline sync identity, cursor, and manual-edit columns (TC-20-050).

Adds ``crm_connections`` (workspace, provider, pipeline, cursor) and deal
columns ``connection_id``, ``provider``, ``crm_stable_id``,
``crm_manual_fields``, and ``crm_removed_at``.

``external_id`` in the unique key is the existing ``deals.crm_external_id``
column. The unique index is partial: a row is included only when
``connection_id``, ``provider``, and ``crm_external_id`` are all non-null, so
manual deals stay unconstrained.

Dedupe, before that index is created: ``provider`` is copied from
``crm_source`` when that source is ``salesforce`` or ``hubspot`` and
``provider`` is still null. Two rows are duplicates when they share
``workspace_id``, ``provider``, and ``crm_external_id``, and their
``connection_id`` values are not distinct (null matches null, because this
upgrade is the first time a connection id exists). The oldest row (smallest
``id``) keeps the identity. Later rows keep company, amount, stage, notes,
and dates. Their ``provider``, ``crm_source``, and ``crm_external_id`` are
cleared and copied to ``tc20050_deal_identity_hold``. Those deals remain.
They are not deleted.

Downgrade drops the unique index first, then writes ``crm_source`` and
``crm_external_id`` back onto a held row when its live ``crm_external_id``
is still null. It then drops the new deal columns, the hold table, and
``crm_connections`` (cursors go with that table). ``provider`` is not written
back because the column is dropped in this downgrade.

down_revision is the single alembic head on master when this file is
parented. Re-parent by changing that one assignment.

Revision ID: tc20050_crm_pipeline_sync
Revises: tc04007b_rate_buckets
"""

from alembic import op
import sqlalchemy as sa

revision = "tc20050_crm_pipeline_sync"
down_revision = "tc04007b_rate_buckets"
branch_labels = None
depends_on = None

_HOLD = "tc20050_deal_identity_hold"
_UNIQUE = "uq_deals_ws_connection_provider_external"


def upgrade() -> None:
    op.create_table(
        "crm_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("pipeline_id", sa.String(length=64), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("cursor_kind", sa.String(length=16), nullable=True),
        sa.Column("seen_external_ids", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "pipeline_id",
            name="uq_crm_connections_ws_provider_pipeline",
        ),
    )
    op.create_index("ix_crm_connections_workspace_id", "crm_connections", ["workspace_id"])
    op.add_column("deals", sa.Column("connection_id", sa.Integer(), nullable=True))
    op.add_column("deals", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column("deals", sa.Column("crm_stable_id", sa.String(length=512), nullable=True))
    op.add_column("deals", sa.Column("crm_manual_fields", sa.Text(), nullable=True))
    op.add_column("deals", sa.Column("crm_removed_at", sa.DateTime(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE deals
            SET provider = crm_source
            WHERE provider IS NULL
              AND crm_source IN ('salesforce', 'hubspot')
            """
        )
    )
    op.create_table(
        _HOLD,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("crm_source", sa.String(length=32), nullable=True),
        sa.UniqueConstraint("deal_id", name="uq_tc20050_deal_identity_hold_deal"),
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"""
            INSERT INTO {_HOLD}
                (deal_id, workspace_id, connection_id, provider, external_id, crm_source)
            SELECT d.id, d.workspace_id, d.connection_id, d.provider,
                   d.crm_external_id, d.crm_source
            FROM deals AS d
            WHERE d.provider IS NOT NULL
              AND d.crm_external_id IS NOT NULL
              AND d.id <> (
                    SELECT MIN(older.id)
                    FROM deals AS older
                    WHERE older.workspace_id = d.workspace_id
                      AND older.provider IS NOT DISTINCT FROM d.provider
                      AND older.crm_external_id = d.crm_external_id
                      AND older.connection_id IS NOT DISTINCT FROM d.connection_id
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM {_HOLD} AS held WHERE held.deal_id = d.id
                  )
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE deals AS d
            SET crm_external_id = NULL,
                provider = NULL,
                crm_source = NULL
            FROM {_HOLD} AS held
            WHERE held.deal_id = d.id
              AND d.crm_external_id IS NOT DISTINCT FROM held.external_id
            """
        )
    )
    op.create_foreign_key(
        "fk_deals_connection_id_crm_connections",
        "deals",
        "crm_connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_deals_connection_id", "deals", ["connection_id"])
    op.create_index(
        _UNIQUE,
        "deals",
        ["workspace_id", "connection_id", "provider", "crm_external_id"],
        unique=True,
        postgresql_where=sa.text(
            "connection_id IS NOT NULL AND provider IS NOT NULL " "AND crm_external_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(_UNIQUE, table_name="deals")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"""
            UPDATE deals AS d
            SET crm_external_id = held.external_id,
                crm_source = held.crm_source
            FROM {_HOLD} AS held
            WHERE held.deal_id = d.id
              AND d.crm_external_id IS NULL
            """
        )
    )
    op.drop_constraint("fk_deals_connection_id_crm_connections", "deals", type_="foreignkey")
    op.drop_index("ix_deals_connection_id", table_name="deals")
    op.drop_column("deals", "crm_removed_at")
    op.drop_column("deals", "crm_manual_fields")
    op.drop_column("deals", "crm_stable_id")
    op.drop_column("deals", "provider")
    op.drop_column("deals", "connection_id")
    op.drop_table(_HOLD)
    op.drop_index("ix_crm_connections_workspace_id", table_name="crm_connections")
    op.drop_table("crm_connections")
