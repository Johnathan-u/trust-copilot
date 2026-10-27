"""Framework catalog version, provenance, rights, and enablement.

Additive columns on frameworks, a backfill that blocks every advertised
framework pending TC-01-007, and an audit table for enablement attempts.
Synthetic dev rows are labelled dev/test only. No control text is written.

Rollback drops the audit table and the new columns. Rows inserted by this
scaffold are deleted only when they have no framework_controls, so a later
control link is not orphaned. Pre-existing framework rows remain.

Revision ID: tc21001_framework_catalog_rights
Revises: 075
"""

import json
from dataclasses import dataclass

from alembic import op
import sqlalchemy as sa

# Frozen snapshot of the catalog constants and helpers this revision needs.
# Intentionally duplicated so later app changes cannot break upgrade or downgrade.
# This module must not import the application package.

revision = "tc21001_framework_catalog_rights"
down_revision = "075"
branch_labels = None
depends_on = None

_CATALOG_CONTRACT_VERSION = "framework-catalog/v1"
_RIGHTS_TICKET = "TC-01-007"
_UNLICENSED_VERSION = "rights-pending"
_RIGHTS_BLOCKED = "blocked_pending_rights"
_RIGHTS_DEV = "dev_test_only"
_LICENCE_NOT_CLEARED = "not_cleared"
_LICENCE_DEV = "dev_test_only"
_ENABLEMENT_BLOCKED = "blocked"
_ENABLEMENT_DEV = "dev_only"
_KIND_ADVERTISED = "advertised_blocked"
_KIND_DEV = "dev_synthetic"
_KIND_LEGACY = "legacy_unclassified"
_CONTENT_NONE = "none"
_CONTENT_DEV = "dev_seed"
_CONTENT_LEGACY = "legacy"
_SEED_FINGERPRINTS = frozenset(
    {
        ("soc2", "2024"),
        ("hipaa", "security rule"),
        ("nist", "csf-2.0"),
        ("hitrust", "csf-dev"),
        ("iso27001", "dev-themes"),
    }
)


def _normalize_catalog_name(value: str | None) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _is_synthetic_dev_version(version: str | None) -> bool:
    if not version:
        return False
    folded = version.strip().lower()
    if folded in {"csf-dev", "dev-themes"}:
        return True
    if "dev theme" in folded or "dev-theme" in folded:
        return True
    if folded.startswith("dev-") or folded.endswith("-dev"):
        return True
    return False


def _is_synthetic_dev_control_key(control_key: str | None) -> bool:
    if not control_key:
        return False
    token = control_key.strip().upper()
    return (
        token.startswith("HITRUST-DEV-")
        or token.startswith("ISO-DEV-")
        or token.startswith("DEV-")
        or "-DEV-" in token
    )


def _is_dev_catalog_row(
    name: str | None, version: str | None, control_keys: list[str] | tuple[str, ...]
) -> bool:
    if _is_synthetic_dev_version(version):
        return True
    if any(_is_synthetic_dev_control_key(key) for key in control_keys):
        return True
    if control_keys:
        fingerprint = (_normalize_catalog_name(name), (version or "").strip().lower())
        if fingerprint in _SEED_FINGERPRINTS:
            return True
    return False


@dataclass(frozen=True)
class _AdvertisedCatalog:
    catalog_key: str
    name: str
    aliases: tuple[str, ...]

    def match_norms(self) -> frozenset[str]:
        values = {self.catalog_key, self.name, *self.aliases}
        return frozenset(
            _normalize_catalog_name(value) for value in values if _normalize_catalog_name(value)
        )


_ADVERTISED_CATALOGS: tuple[_AdvertisedCatalog, ...] = (
    _AdvertisedCatalog("SOC2", "SOC 2", ("SOC2", "SOC 2", "SOC II", "SOC-2")),
    _AdvertisedCatalog("HIPAA", "HIPAA", ("HIPAA",)),
    _AdvertisedCatalog(
        "ISO27001", "ISO 27001", ("ISO27001", "ISO 27001", "ISO/IEC 27001", "ISO/IEC27001")
    ),
    _AdvertisedCatalog(
        "NIST_CSF_2",
        "NIST CSF 2",
        ("NIST CSF 2", "NIST CSF 2.0", "NIST CSF", "CSF 2.0", "NIST Cybersecurity Framework"),
    ),
    _AdvertisedCatalog(
        "NIST_800_53_R5",
        "NIST 800-53r5",
        (
            "NIST 800-53r5",
            "NIST 800-53",
            "NIST SP 800-53",
            "NIST SP 800-53 Rev. 5",
            "NIST SP 800-53 Rev 5",
            "800-53",
        ),
    ),
    _AdvertisedCatalog(
        "NIST_800_171_R3",
        "NIST 800-171r3",
        (
            "NIST 800-171r3",
            "NIST 800-171",
            "NIST SP 800-171",
            "NIST SP 800-171 Rev. 3",
            "NIST SP 800-171 Rev 3",
        ),
    ),
    _AdvertisedCatalog("SIG", "SIG", ("SIG", "Shared Assessments SIG", "Shared Assessments")),
    _AdvertisedCatalog("CAIQ", "CAIQ", ("CAIQ", "CSA CAIQ")),
    _AdvertisedCatalog("HITRUST", "HITRUST", ("HITRUST", "HITRUST CSF")),
)


def _provenance_json(kind: str) -> str:
    if kind == _KIND_DEV:
        payload = {
            "kind": "dev_seed",
            "origin": "development-only catalog seed",
            "content_included": False,
            "licensed_text_included": False,
            "dev_test_only": True,
            "production_catalog": False,
            "rights_decision": "pending",
            "rights_ticket": _RIGHTS_TICKET,
        }
    elif kind == _KIND_LEGACY:
        payload = {
            "kind": "legacy_row",
            "origin": "pre-catalog framework row",
            "content_included": False,
            "licensed_text_included": False,
            "dev_test_only": False,
            "production_catalog": False,
            "rights_decision": "pending",
            "rights_ticket": _RIGHTS_TICKET,
        }
    else:
        payload = {
            "kind": "scaffold",
            "origin": "in-repo advertised catalog registry",
            "content_included": False,
            "licensed_text_included": False,
            "dev_test_only": False,
            "production_catalog": False,
            "rights_decision": "pending",
            "rights_ticket": _RIGHTS_TICKET,
        }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


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
            sa.ForeignKey("frameworks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(32), nullable=True),
        sa.Column("catalog_key", sa.String(64), nullable=True),
        sa.Column("name", sa.String(64), nullable=True),
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
        "production_catalog = false AND "
        "(enablement_state IS NULL OR enablement_state IN ('blocked', 'dev_only'))",
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
        if _is_dev_catalog_row(row["name"], row["version"], control_keys):
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
                    "kind": _KIND_DEV,
                    "enablement": _ENABLEMENT_DEV,
                    "rights": _RIGHTS_DEV,
                    "licence": _LICENCE_DEV,
                    "origin": _CONTENT_DEV,
                    "ticket": _RIGHTS_TICKET,
                    "contract": _CATALOG_CONTRACT_VERSION,
                    "provenance": _provenance_json(_KIND_DEV),
                },
            )

    chosen_ids: set[int] = set()
    for spec in _ADVERTISED_CATALOGS:
        match_id = None
        for row in frameworks:
            if row["id"] in dev_ids:
                continue
            if _normalize_catalog_name(row["name"]) in spec.match_norms():
                match_id = row["id"]
                break
        if match_id is not None:
            control_count = len(keys_by_framework.get(match_id, []))
            bind.execute(
                sa.text(
                    """
                    UPDATE frameworks
                    SET catalog_key = :catalog_key,
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
                    "catalog_key": spec.catalog_key,
                    "kind": _KIND_ADVERTISED,
                    "enablement": _ENABLEMENT_BLOCKED,
                    "rights": _RIGHTS_BLOCKED,
                    "licence": _LICENCE_NOT_CLEARED,
                    "origin": _CONTENT_LEGACY if control_count else _CONTENT_NONE,
                    "ticket": _RIGHTS_TICKET,
                    "contract": _CATALOG_CONTRACT_VERSION,
                    "provenance": _provenance_json(_KIND_ADVERTISED),
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
                )
                SELECT
                    :name, :version, now(), :catalog_key, :provenance, :rights,
                    :licence, :enablement, :kind, :ticket, :contract,
                    :origin, true, false, now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM frameworks WHERE catalog_key = :catalog_key
                )
                AND NOT EXISTS (
                    SELECT 1 FROM frameworks WHERE name = :name
                )
                """
            ),
            {
                "name": spec.name,
                "version": _UNLICENSED_VERSION,
                "catalog_key": spec.catalog_key,
                "provenance": _provenance_json(_KIND_ADVERTISED),
                "rights": _RIGHTS_BLOCKED,
                "licence": _LICENCE_NOT_CLEARED,
                "enablement": _ENABLEMENT_BLOCKED,
                "kind": _KIND_ADVERTISED,
                "ticket": _RIGHTS_TICKET,
                "contract": _CATALOG_CONTRACT_VERSION,
                "origin": _CONTENT_NONE,
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
                "kind": _KIND_LEGACY,
                "enablement": _ENABLEMENT_BLOCKED,
                "rights": _RIGHTS_BLOCKED,
                "licence": _LICENCE_NOT_CLEARED,
                "origin": _CONTENT_LEGACY,
                "ticket": _RIGHTS_TICKET,
                "contract": _CATALOG_CONTRACT_VERSION,
                "provenance": _provenance_json(_KIND_LEGACY),
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
            DELETE FROM frameworks AS scaffold_row
            WHERE scaffold_row.scaffold_inserted IS TRUE
              AND NOT EXISTS (
                    SELECT 1 FROM framework_controls AS child
                    WHERE child.framework_id = scaffold_row.id
              )
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
