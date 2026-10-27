"""Consent-backed case study publication (TC-25-005).

Revision ID: tc25005_case_study_consent
Revises: tc11001_model_outcome_codes

Parent is master's current head, tc11001_model_outcome_codes (PR #16), which
itself revises tc21001_framework_catalog_rights. PR #30 (tc25011) re-parents
onto that same head. Whichever of this revision and tc25011 merges second
re-parents onto the other. Do not reuse the numeric id 076.

Upgrade adds columns and consent tables. It never deletes a case study row.
Existing published rows have no consent evidence, so the first upgrade copies
status and published_at into pre_consent_status / pre_consent_published_at and
moves those published rows back to draft.

Downgrade is lossless for the time the database stays on the parent revision.
Before it drops the live consent tables and the new columns, it copies consent
rows, permission rows, and per-row review, revision, and content fingerprint
metadata into archive tables that have no foreign keys. Snapshot status and
published_at are written back only for rows that are still in the exact state
this upgrade left them in. A later workflow change is left alone.

Re-upgrade loads those archives back into the live tables, then drops the
archive tables. Published status is restored only when the live status and the
content fingerprint still match the archive. Otherwise the row returns as a
draft at revision+1 so the old consent no longer covers it. A row with no
restored active consent is not published as a customer claim.

This module does not import the application package.
"""

from alembic import op
import sqlalchemy as sa

revision = "tc25005_case_study_consent"
down_revision = "tc11001_model_outcome_codes"
branch_labels = None
depends_on = None

# Columns that still exist on the parent revision. quoted_organizations_json is
# archived and restored, but it is not part of this match: the parent revision
# does not have that column, so it cannot drift while downgraded.
_FINGERPRINT_MATCH = """
    cs.status IS NOT DISTINCT FROM a.status_at_archive
    AND cs.title IS NOT DISTINCT FROM a.title
    AND cs.challenge IS NOT DISTINCT FROM a.challenge
    AND cs.solution IS NOT DISTINCT FROM a.solution
    AND cs.quote IS NOT DISTINCT FROM a.quote
    AND cs.results IS NOT DISTINCT FROM a.results
    AND cs.metrics_json IS NOT DISTINCT FROM a.metrics_json
    AND cs.company_name IS NOT DISTINCT FROM a.company_name
"""

_EXACT_UPGRADE_STATE = """
    cs.pre_consent_status IS NOT NULL
    AND cs.review_status = 'none'
    AND cs.revision = 1
    AND cs.customer_claim IS FALSE
    AND cs.publication_authorized IS FALSE
    AND cs.synthetic IS FALSE
    AND cs.data_basis = 'unverified'
    AND cs.reviewed_at IS NULL
    AND cs.reviewed_by_user_id IS NULL
    AND cs.schema_version = 'case-study.v2'
    AND cs.quoted_organizations_json IS NULL
    AND (
        (
            cs.pre_consent_status = 'published'
            AND cs.status = 'draft'
            AND cs.published_at IS NULL
        )
        OR (
            cs.pre_consent_status <> 'published'
            AND cs.status = cs.pre_consent_status
            AND cs.published_at IS NOT DISTINCT FROM cs.pre_consent_published_at
        )
    )
"""


def _relation_exists(name: str) -> bool:
    found = (
        op.get_bind()
        .execute(
            sa.text("SELECT to_regclass(:name)"),
            {"name": f"public.{name}"},
        )
        .scalar()
    )
    return found is not None


def _restart_id_sequence(table: str) -> None:
    bind = op.get_bind()
    max_id = bind.execute(sa.text(f"SELECT MAX(id) FROM {table}")).scalar()
    if max_id is None:
        return
    sequence = bind.execute(
        sa.text("SELECT pg_get_serial_sequence(:table, 'id')"),
        {"table": f"public.{table}"},
    ).scalar()
    if not sequence:
        raise RuntimeError(f"no id sequence for {table}")
    bind.execute(sa.text("SELECT setval(:seq, :n)"), {"seq": sequence, "n": max_id})


def _backfill_rows_without_archive() -> None:
    """First-upgrade backfill. Unpublishes rows that have no consent. Deletes nothing."""
    op.execute(
        """
        UPDATE case_studies
        SET pre_consent_status = status,
            pre_consent_published_at = published_at,
            synthetic = FALSE,
            customer_claim = FALSE,
            publication_authorized = FALSE,
            data_basis = 'unverified',
            review_status = 'none',
            revision = 1,
            schema_version = 'case-study.v2'
        """
    )
    op.execute(
        """
        UPDATE case_studies
        SET status = 'draft',
            published_at = NULL
        WHERE pre_consent_status = 'published'
        """
    )


def _backfill_rows_created_while_downgraded() -> None:
    """Rows inserted after downgrade are not in the archive. Treat them as a first upgrade."""
    op.execute(
        """
        UPDATE case_studies AS cs
        SET pre_consent_status = cs.status,
            pre_consent_published_at = cs.published_at,
            synthetic = FALSE,
            customer_claim = FALSE,
            publication_authorized = FALSE,
            data_basis = 'unverified',
            review_status = 'none',
            revision = 1,
            schema_version = 'case-study.v2'
        WHERE NOT EXISTS (
            SELECT 1
            FROM case_study_review_archive AS a
            WHERE a.case_study_id = cs.id
        )
        """
    )
    op.execute(
        """
        UPDATE case_studies AS cs
        SET status = 'draft',
            published_at = NULL
        WHERE cs.pre_consent_status = 'published'
          AND NOT EXISTS (
            SELECT 1
            FROM case_study_review_archive AS a
            WHERE a.case_study_id = cs.id
          )
        """
    )


def _restore_review_archive() -> None:
    """Restore review metadata. Published status returns only when nothing changed.

    The live row is compared before this update overwrites it. A status edit or
    a content edit made on the parent revision bumps revision so archived
    consents no longer match, and the row comes back as a draft.
    """
    op.execute(
        f"""
        UPDATE case_studies AS cs
        SET quoted_organizations_json = a.quoted_organizations_json,
            synthetic = a.synthetic,
            data_basis = CASE
                WHEN {_FINGERPRINT_MATCH} THEN a.data_basis
                WHEN a.synthetic IS TRUE THEN 'synthetic_example'
                ELSE 'unverified'
            END,
            customer_claim = CASE
                WHEN {_FINGERPRINT_MATCH} THEN a.customer_claim
                ELSE FALSE
            END,
            publication_authorized = CASE
                WHEN {_FINGERPRINT_MATCH} THEN a.publication_authorized
                ELSE FALSE
            END,
            review_status = a.review_status,
            revision = CASE
                WHEN {_FINGERPRINT_MATCH} THEN a.revision
                ELSE a.revision + 1
            END,
            schema_version = a.schema_version,
            reviewed_by_user_id = CASE
                WHEN a.reviewed_by_user_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM users AS u WHERE u.id = a.reviewed_by_user_id
                ) THEN a.reviewed_by_user_id
                ELSE NULL
            END,
            reviewed_at = a.reviewed_at,
            pre_consent_status = a.pre_consent_status,
            pre_consent_published_at = a.pre_consent_published_at,
            status = CASE
                WHEN {_FINGERPRINT_MATCH} THEN a.status_at_archive
                ELSE 'draft'
            END,
            published_at = CASE
                WHEN {_FINGERPRINT_MATCH} THEN a.published_at_at_archive
                ELSE NULL
            END
        FROM case_study_review_archive AS a
        WHERE cs.id = a.case_study_id
        """
    )


def _restore_consent_archive() -> None:
    if not _relation_exists("case_study_consent_archive"):
        return
    op.execute(
        """
        INSERT INTO case_study_organization_consents (
            id, workspace_id, case_study_id, organization_name, consent_reference,
            consent_granted, granted_revision, granted_by_user_id, created_at, revoked_at
        )
        SELECT
            a.id,
            a.workspace_id,
            a.case_study_id,
            a.organization_name,
            a.consent_reference,
            a.consent_granted,
            a.granted_revision,
            CASE
                WHEN a.granted_by_user_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM users AS u WHERE u.id = a.granted_by_user_id
                ) THEN a.granted_by_user_id
                ELSE NULL
            END,
            a.created_at,
            a.revoked_at
        FROM case_study_consent_archive AS a
        WHERE EXISTS (
            SELECT 1 FROM case_studies AS cs
            WHERE cs.id = a.case_study_id AND cs.workspace_id = a.workspace_id
        )
        AND EXISTS (SELECT 1 FROM workspaces AS w WHERE w.id = a.workspace_id)
        """
    )
    _restart_id_sequence("case_study_organization_consents")

    if not _relation_exists("case_study_result_permission_archive"):
        return
    op.execute(
        """
        INSERT INTO case_study_result_permissions (
            id, workspace_id, case_study_id, consent_id, result_key, permitted,
            granted_revision, granted_by_user_id, created_at, revoked_at
        )
        SELECT
            a.id,
            a.workspace_id,
            a.case_study_id,
            a.consent_id,
            a.result_key,
            a.permitted,
            a.granted_revision,
            CASE
                WHEN a.granted_by_user_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM users AS u WHERE u.id = a.granted_by_user_id
                ) THEN a.granted_by_user_id
                ELSE NULL
            END,
            a.created_at,
            a.revoked_at
        FROM case_study_result_permission_archive AS a
        WHERE EXISTS (
            SELECT 1 FROM case_study_organization_consents AS c
            WHERE c.id = a.consent_id AND c.case_study_id = a.case_study_id
        )
        AND EXISTS (
            SELECT 1 FROM case_studies AS cs
            WHERE cs.id = a.case_study_id AND cs.workspace_id = a.workspace_id
        )
        """
    )
    _restart_id_sequence("case_study_result_permissions")


def _clear_claims_without_consent() -> None:
    """Do not bring back a customer claim or an unconsented publication."""
    op.execute(
        """
        UPDATE case_studies AS cs
        SET customer_claim = FALSE,
            publication_authorized = FALSE,
            status = 'draft',
            published_at = NULL,
            data_basis = CASE
                WHEN cs.data_basis = 'consented_customer' THEN 'unverified'
                ELSE cs.data_basis
            END
        WHERE cs.synthetic IS FALSE
          AND (
                cs.customer_claim IS TRUE
                OR cs.status = 'published'
                OR cs.publication_authorized IS TRUE
                OR cs.data_basis = 'consented_customer'
          )
          AND NOT EXISTS (
                SELECT 1
                FROM case_study_organization_consents AS c
                WHERE c.case_study_id = cs.id
                  AND c.revoked_at IS NULL
                  AND c.consent_granted IS TRUE
          )
        """
    )


def _create_consent_tables() -> None:
    op.create_unique_constraint(
        "uq_case_studies_id_workspace",
        "case_studies",
        ["id", "workspace_id"],
    )

    op.create_table(
        "case_study_organization_consents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_study_id", sa.Integer(), nullable=False),
        sa.Column("organization_name", sa.String(255), nullable=False),
        sa.Column("consent_reference", sa.String(255), nullable=True),
        sa.Column("consent_granted", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("granted_revision", sa.Integer(), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name="fk_case_study_consent_granted_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_study_id", "workspace_id"],
            ["case_studies.id", "case_studies.workspace_id"],
            name="fk_case_study_consent_case_workspace",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "case_study_id", name="uq_case_study_consent_id_case"),
    )
    op.create_index(
        "ix_case_study_org_consent_workspace",
        "case_study_organization_consents",
        ["workspace_id"],
    )
    op.create_index(
        "ix_case_study_org_consent_case",
        "case_study_organization_consents",
        ["case_study_id"],
    )
    op.create_index(
        "uq_case_study_org_consent_active",
        "case_study_organization_consents",
        ["case_study_id", "organization_name"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "case_study_result_permissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_study_id", sa.Integer(), nullable=False),
        sa.Column("consent_id", sa.Integer(), nullable=False),
        sa.Column("result_key", sa.String(128), nullable=False),
        sa.Column("permitted", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("granted_revision", sa.Integer(), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name="fk_case_study_perm_granted_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_study_id", "workspace_id"],
            ["case_studies.id", "case_studies.workspace_id"],
            name="fk_case_study_perm_case_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["consent_id", "case_study_id"],
            [
                "case_study_organization_consents.id",
                "case_study_organization_consents.case_study_id",
            ],
            name="fk_case_study_perm_consent_case",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_case_study_result_perm_workspace",
        "case_study_result_permissions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_case_study_result_perm_case",
        "case_study_result_permissions",
        ["case_study_id"],
    )
    op.create_index(
        "ix_case_study_result_perm_consent",
        "case_study_result_permissions",
        ["consent_id"],
    )
    op.create_index(
        "uq_case_study_result_perm_active",
        "case_study_result_permissions",
        ["consent_id", "result_key"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def _drop_archive_tables() -> None:
    """Archives exist only while this revision is downgraded. Re-upgrade drops them."""
    op.execute("DROP TABLE IF EXISTS case_study_result_permission_archive")
    op.execute("DROP TABLE IF EXISTS case_study_consent_archive")
    op.execute("DROP TABLE IF EXISTS case_study_review_archive")


def _ensure_archive_tables() -> None:
    """Recreate archive tables with no foreign keys. A previous shape is replaced."""
    _drop_archive_tables()
    op.execute(
        """
        CREATE TABLE case_study_consent_archive (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER NOT NULL,
            case_study_id INTEGER NOT NULL,
            organization_name VARCHAR(255) NOT NULL,
            consent_reference VARCHAR(255),
            consent_granted BOOLEAN NOT NULL,
            granted_revision INTEGER NOT NULL,
            granted_by_user_id INTEGER,
            created_at TIMESTAMP WITH TIME ZONE,
            revoked_at TIMESTAMP WITH TIME ZONE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE case_study_result_permission_archive (
            id INTEGER PRIMARY KEY,
            workspace_id INTEGER NOT NULL,
            case_study_id INTEGER NOT NULL,
            consent_id INTEGER NOT NULL,
            result_key VARCHAR(128) NOT NULL,
            permitted BOOLEAN NOT NULL,
            granted_revision INTEGER NOT NULL,
            granted_by_user_id INTEGER,
            created_at TIMESTAMP WITH TIME ZONE,
            revoked_at TIMESTAMP WITH TIME ZONE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE case_study_review_archive (
            case_study_id INTEGER PRIMARY KEY,
            workspace_id INTEGER NOT NULL,
            quoted_organizations_json TEXT,
            title VARCHAR(512) NOT NULL,
            challenge TEXT,
            solution TEXT,
            quote TEXT,
            results TEXT,
            metrics_json TEXT,
            company_name VARCHAR(255),
            synthetic BOOLEAN NOT NULL,
            data_basis VARCHAR(32) NOT NULL,
            customer_claim BOOLEAN NOT NULL,
            publication_authorized BOOLEAN NOT NULL,
            review_status VARCHAR(32) NOT NULL,
            revision INTEGER NOT NULL,
            schema_version VARCHAR(32) NOT NULL,
            reviewed_by_user_id INTEGER,
            reviewed_at TIMESTAMP WITH TIME ZONE,
            pre_consent_status VARCHAR(32),
            pre_consent_published_at TIMESTAMP WITH TIME ZONE,
            status_at_archive VARCHAR(32) NOT NULL,
            published_at_at_archive TIMESTAMP WITH TIME ZONE,
            snapshot_restored BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )


def _archive_live_rows() -> None:
    op.execute(
        """
        INSERT INTO case_study_review_archive (
            case_study_id, workspace_id, quoted_organizations_json, title, challenge, solution,
            quote, results, metrics_json, company_name, synthetic, data_basis,
            customer_claim, publication_authorized, review_status, revision, schema_version,
            reviewed_by_user_id, reviewed_at, pre_consent_status, pre_consent_published_at,
            status_at_archive, published_at_at_archive, snapshot_restored
        )
        SELECT
            id, workspace_id, quoted_organizations_json, title, challenge, solution,
            quote, results, metrics_json, company_name, synthetic, data_basis,
            customer_claim, publication_authorized, review_status, revision, schema_version,
            reviewed_by_user_id, reviewed_at, pre_consent_status, pre_consent_published_at,
            status, published_at, FALSE
        FROM case_studies
        """
    )
    op.execute(
        """
        INSERT INTO case_study_consent_archive (
            id, workspace_id, case_study_id, organization_name, consent_reference,
            consent_granted, granted_revision, granted_by_user_id, created_at, revoked_at
        )
        SELECT
            id, workspace_id, case_study_id, organization_name, consent_reference,
            consent_granted, granted_revision, granted_by_user_id, created_at, revoked_at
        FROM case_study_organization_consents
        """
    )
    op.execute(
        """
        INSERT INTO case_study_result_permission_archive (
            id, workspace_id, case_study_id, consent_id, result_key, permitted,
            granted_revision, granted_by_user_id, created_at, revoked_at
        )
        SELECT
            id, workspace_id, case_study_id, consent_id, result_key, permitted,
            granted_revision, granted_by_user_id, created_at, revoked_at
        FROM case_study_result_permissions
        """
    )
    op.execute(
        f"""
        UPDATE case_study_review_archive AS a
        SET snapshot_restored = TRUE
        FROM case_studies AS cs
        WHERE cs.id = a.case_study_id
          AND {_EXACT_UPGRADE_STATE}
        """
    )
    op.execute(
        """
        UPDATE case_studies AS cs
        SET status = cs.pre_consent_status,
            published_at = cs.pre_consent_published_at
        FROM case_study_review_archive AS a
        WHERE cs.id = a.case_study_id
          AND a.snapshot_restored IS TRUE
        """
    )


def upgrade() -> None:
    op.add_column(
        "case_studies",
        sa.Column("quoted_organizations_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "case_studies",
        sa.Column("synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "case_studies",
        sa.Column(
            "data_basis",
            sa.String(32),
            nullable=False,
            server_default="unverified",
        ),
    )
    op.add_column(
        "case_studies",
        sa.Column("customer_claim", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "case_studies",
        sa.Column(
            "publication_authorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "case_studies",
        sa.Column("review_status", sa.String(32), nullable=False, server_default="none"),
    )
    op.add_column(
        "case_studies",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "case_studies",
        sa.Column(
            "schema_version",
            sa.String(32),
            nullable=False,
            server_default="case-study.v2",
        ),
    )
    op.add_column(
        "case_studies",
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "case_studies",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "case_studies",
        sa.Column("pre_consent_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "case_studies",
        sa.Column("pre_consent_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_case_studies_reviewed_by_user",
        "case_studies",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Archive tables are created by downgrade and are not part of this revision's
    # schema. Their presence means this upgrade is a re-upgrade.
    if _relation_exists("case_study_review_archive"):
        _restore_review_archive()
        _backfill_rows_created_while_downgraded()
    else:
        _backfill_rows_without_archive()

    _create_consent_tables()

    if _relation_exists("case_study_review_archive"):
        _restore_consent_archive()
        _clear_claims_without_consent()

    _drop_archive_tables()


def downgrade() -> None:
    _ensure_archive_tables()
    _archive_live_rows()
    op.drop_index("uq_case_study_result_perm_active", table_name="case_study_result_permissions")
    op.drop_index("ix_case_study_result_perm_consent", table_name="case_study_result_permissions")
    op.drop_index("ix_case_study_result_perm_case", table_name="case_study_result_permissions")
    op.drop_index("ix_case_study_result_perm_workspace", table_name="case_study_result_permissions")
    op.drop_table("case_study_result_permissions")
    op.drop_index("uq_case_study_org_consent_active", table_name="case_study_organization_consents")
    op.drop_index("ix_case_study_org_consent_case", table_name="case_study_organization_consents")
    op.drop_index(
        "ix_case_study_org_consent_workspace", table_name="case_study_organization_consents"
    )
    op.drop_table("case_study_organization_consents")
    op.drop_constraint("uq_case_studies_id_workspace", "case_studies", type_="unique")
    op.drop_constraint("fk_case_studies_reviewed_by_user", "case_studies", type_="foreignkey")
    op.drop_column("case_studies", "pre_consent_published_at")
    op.drop_column("case_studies", "pre_consent_status")
    op.drop_column("case_studies", "reviewed_at")
    op.drop_column("case_studies", "reviewed_by_user_id")
    op.drop_column("case_studies", "schema_version")
    op.drop_column("case_studies", "revision")
    op.drop_column("case_studies", "review_status")
    op.drop_column("case_studies", "publication_authorized")
    op.drop_column("case_studies", "customer_claim")
    op.drop_column("case_studies", "data_basis")
    op.drop_column("case_studies", "synthetic")
    op.drop_column("case_studies", "quoted_organizations_json")
