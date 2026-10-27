"""Consent-backed case study publication (TC-25-005).

Revision ID: 076
Revises: 075

Additive columns and consent tables. Existing published rows have no consent
evidence, so the backfill clears publication and stores the previous status in
pre_consent_status / pre_consent_published_at for downgrade.

Downgrade restores that snapshot, then drops the consent tables. Consent rows
created after this revision cannot survive a downgrade. A later upgrade treats
any remaining published row as unconsented and clears it again, so a dropped
consent cannot come back as a customer claim.
"""

from alembic import op
import sqlalchemy as sa

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


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

    # Backfill: remember the pre-migration status, then clear every customer-claim flag.
    # Published rows had no consent records, so they must not stay published.
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
            ["case_study_organization_consents.id", "case_study_organization_consents.case_study_id"],
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


def downgrade() -> None:
    op.execute(
        """
        UPDATE case_studies
        SET status = COALESCE(pre_consent_status, status),
            published_at = pre_consent_published_at
        WHERE pre_consent_status IS NOT NULL
        """
    )
    op.drop_index("uq_case_study_result_perm_active", table_name="case_study_result_permissions")
    op.drop_index("ix_case_study_result_perm_consent", table_name="case_study_result_permissions")
    op.drop_index("ix_case_study_result_perm_case", table_name="case_study_result_permissions")
    op.drop_index("ix_case_study_result_perm_workspace", table_name="case_study_result_permissions")
    op.drop_table("case_study_result_permissions")
    op.drop_index("uq_case_study_org_consent_active", table_name="case_study_organization_consents")
    op.drop_index("ix_case_study_org_consent_case", table_name="case_study_organization_consents")
    op.drop_index("ix_case_study_org_consent_workspace", table_name="case_study_organization_consents")
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
