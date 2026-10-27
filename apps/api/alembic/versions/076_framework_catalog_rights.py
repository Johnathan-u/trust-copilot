"""Framework catalog version, provenance, rights, and enablement.

Additive columns on frameworks, a backfill that blocks every advertised
framework pending TC-01-007, and an audit table for enablement attempts.
Synthetic dev rows are labelled dev/test only. No control text is written.

Rollback drops the audit table and the new columns. Rows inserted by this
scaffold are deleted only when they have no framework_controls, so a later
control link is not orphaned. Pre-existing framework rows remain.

Revision ID: 076
Revises: 075
"""

from alembic import op
import sqlalchemy as sa

from app.services.framework_catalog_registry import (
    ADVERTISED_CATALOGS,
    CATALOG_CONTRACT_VERSION,
    CONTENT_DEV,
    CONTENT_LEGACY,
    CONTENT_NONE,
    ENABLEMENT_BLOCKED,
    ENABLEMENT_DEV,
    KIND_ADVERTISED,
    KIND_DEV,
    KIND_LEGACY,
    LICENCE_DEV,
    LICENCE_NOT_CLEARED,
    RIGHTS_BLOCKED,
    RIGHTS_DEV,
    RIGHTS_TICKET,
    UNLICENSED_VERSION,
    is_dev_catalog_row,
    normalize_catalog_name,
    provenance_json,
)

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("frameworks", sa.Column("catalog_key", sa.String(64), nullable=True))
    op.add_column("frameworks", sa.Column("source_provenance", sa.Text(), nullable=True))
    op.add_column("frameworks", sa.Column("rights_status", sa.String(64), nullable=True))
    op.add_column("frameworks", sa.Column("licence_status", sa.String(64), nullable=True))
    op.add_column("frameworks", sa.Column("enablement_state", sa.String(32), nullable=True))
    op.add_column("frameworks", sa.Column("catalog_kind", sa.String(32), nullable=True))
    op.add_column("frameworks", sa.Column("rights_ticket", sa.String(32), nullable=True))
    op.add_column("frameworks", sa.Column("contract_version", sa.String(64), nullable=True))
    op.add_column("frameworks", sa.Column("content_origin", sa.String(32), nullable=True))
    op.add_column(
        "frameworks",
        sa.Column("scaffold_inserted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "frameworks",
        sa.Column("production_catalog", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("frameworks", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.create_table(
        "framework_catalog_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "framework_id",
            sa.Integer(),
            sa.ForeignKey("frameworks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(32), nullable=True),
        sa.Column("catalog_key", sa.String(64), nullable=True),
        sa.Column("attempted_version", sa.String(32), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_framework_catalog_events_framework_id", "framework_catalog_events", ["framework_id"]
    )
    op.create_index(
        "ix_framework_catalog_events_workspace_id", "framework_catalog_events", ["workspace_id"]
    )
    op.create_index(
        "ix_framework_catalog_events_actor_user_id", "framework_catalog_events", ["actor_user_id"]
    )

    _backfill()

    op.create_index("uq_frameworks_catalog_key", "frameworks", ["catalog_key"], unique=True)
    op.create_check_constraint(
        "ck_frameworks_production_blocked",
        "frameworks",
        "production_catalog = false AND (enablement_state IS NULL OR enablement_state IN ('blocked', 'dev_only'))",
    )


def _backfill() -> None:
    bind = op.get_bind()
    frameworks = (
        bind.execute(sa.text("SELECT id, name, version FROM frameworks ORDER BY id"))
        .mappings()
        .all()
    )
    control_rows = (
        bind.execute(sa.text("SELECT framework_id, control_key FROM framework_controls"))
        .mappings()
        .all()
    )
    keys_by_framework: dict[int, list[str]] = {}
    for control in control_rows:
        keys_by_framework.setdefault(control["framework_id"], []).append(
            control["control_key"] or ""
        )

    dev_ids: set[int] = set()
    for row in frameworks:
        control_keys = keys_by_framework.get(row["id"], [])
        if is_dev_catalog_row(row["name"], row["version"], control_keys):
            dev_ids.add(row["id"])
            bind.execute(
                sa.text(
                    """
                    UPDATE frameworks
                    SET catalog_key = NULL,
                        catalog_kind = :kind,
                        enablement_state = :enablement,
                        rights_status = :rights,
                        licence_status = :licence,
                        content_origin = :origin,
                        rights_ticket = :ticket,
                        contract_version = :contract,
                        production_catalog = false,
                        source_provenance = :provenance,
                        updated_at = now()
                    WHERE id = :id
                    """
                ),
                {
                    "id": row["id"],
                    "kind": KIND_DEV,
                    "enablement": ENABLEMENT_DEV,
                    "rights": RIGHTS_DEV,
                    "licence": LICENCE_DEV,
                    "origin": CONTENT_DEV,
                    "ticket": RIGHTS_TICKET,
                    "contract": CATALOG_CONTRACT_VERSION,
                    "provenance": provenance_json(KIND_DEV),
                },
            )

    chosen_ids: set[int] = set()
    for spec in ADVERTISED_CATALOGS:
        match_id = None
        for row in frameworks:
            if row["id"] in dev_ids:
                continue
            if normalize_catalog_name(row["name"]) in spec.match_norms():
                match_id = row["id"]
                break
        if match_id is not None:
            original = next(row for row in frameworks if row["id"] == match_id)
            version = original["version"]
            if not (version and str(version).strip()):
                version = UNLICENSED_VERSION
            control_count = len(keys_by_framework.get(match_id, []))
            bind.execute(
                sa.text(
                    """
                    UPDATE frameworks
                    SET name = :name,
                        version = :version,
                        catalog_key = :catalog_key,
                        catalog_kind = :kind,
                        enablement_state = :enablement,
                        rights_status = :rights,
                        licence_status = :licence,
                        content_origin = :origin,
                        rights_ticket = :ticket,
                        contract_version = :contract,
                        production_catalog = false,
                        scaffold_inserted = false,
                        source_provenance = :provenance,
                        updated_at = now()
                    WHERE id = :id
                    """
                ),
                {
                    "id": match_id,
                    "name": spec.name,
                    "version": version,
                    "catalog_key": spec.catalog_key,
                    "kind": KIND_ADVERTISED,
                    "enablement": ENABLEMENT_BLOCKED,
                    "rights": RIGHTS_BLOCKED,
                    "licence": LICENCE_NOT_CLEARED,
                    "origin": CONTENT_LEGACY if control_count else CONTENT_NONE,
                    "ticket": RIGHTS_TICKET,
                    "contract": CATALOG_CONTRACT_VERSION,
                    "provenance": provenance_json(KIND_ADVERTISED),
                },
            )
            chosen_ids.add(match_id)
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO frameworks (
                    name, version, created_at, catalog_key, source_provenance, rights_status,
                    licence_status, enablement_state, catalog_kind, rights_ticket, contract_version,
                    content_origin, scaffold_inserted, production_catalog, updated_at
                ) VALUES (
                    :name, :version, now(), :catalog_key, :provenance, :rights,
                    :licence, :enablement, :kind, :ticket, :contract,
                    :origin, true, false, now()
                )
                """
            ),
            {
                "name": spec.name,
                "version": UNLICENSED_VERSION,
                "catalog_key": spec.catalog_key,
                "provenance": provenance_json(KIND_ADVERTISED),
                "rights": RIGHTS_BLOCKED,
                "licence": LICENCE_NOT_CLEARED,
                "enablement": ENABLEMENT_BLOCKED,
                "kind": KIND_ADVERTISED,
                "ticket": RIGHTS_TICKET,
                "contract": CATALOG_CONTRACT_VERSION,
                "origin": CONTENT_NONE,
            },
        )
    for row in frameworks:
        if row["id"] in dev_ids or row["id"] in chosen_ids:
            continue
        bind.execute(
            sa.text(
                """
                UPDATE frameworks
                SET catalog_key = NULL,
                    catalog_kind = :kind,
                    enablement_state = :enablement,
                    rights_status = :rights,
                    licence_status = :licence,
                    content_origin = :origin,
                    rights_ticket = :ticket,
                    contract_version = :contract,
                    production_catalog = false,
                    source_provenance = :provenance,
                    updated_at = now()
                WHERE id = :id AND catalog_key IS NULL
                """
            ),
            {
                "id": row["id"],
                "kind": KIND_LEGACY,
                "enablement": ENABLEMENT_BLOCKED,
                "rights": RIGHTS_BLOCKED,
                "licence": LICENCE_NOT_CLEARED,
                "origin": CONTENT_LEGACY,
                "ticket": RIGHTS_TICKET,
                "contract": CATALOG_CONTRACT_VERSION,
                "provenance": provenance_json(KIND_LEGACY),
            },
        )


def downgrade() -> None:
    op.drop_constraint("ck_frameworks_production_blocked", "frameworks", type_="check")
    op.drop_index("uq_frameworks_catalog_key", table_name="frameworks")
    op.drop_index(
        "ix_framework_catalog_events_actor_user_id", table_name="framework_catalog_events"
    )
    op.drop_index("ix_framework_catalog_events_workspace_id", table_name="framework_catalog_events")
    op.drop_index("ix_framework_catalog_events_framework_id", table_name="framework_catalog_events")
    op.drop_table("framework_catalog_events")
    op.execute(
        sa.text(
            """
            DELETE FROM frameworks
            WHERE scaffold_inserted IS TRUE
              AND id NOT IN (SELECT DISTINCT framework_id FROM framework_controls)
            """
        )
    )
    for column in (
        "updated_at",
        "production_catalog",
        "scaffold_inserted",
        "content_origin",
        "contract_version",
        "rights_ticket",
        "catalog_kind",
        "enablement_state",
        "licence_status",
        "rights_status",
        "source_provenance",
        "catalog_key",
    ):
        op.drop_column("frameworks", column)
