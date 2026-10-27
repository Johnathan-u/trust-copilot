"""Case study authoring model (P0-83, TC-25-005).

Publication is not a customer claim unless the workflow has recorded consent
for every quoted organization and permission for every quoted result.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)

from app.core.database import Base

SCHEMA_VERSION = "case-study.v2"

DATA_BASIS_UNVERIFIED = "unverified"
DATA_BASIS_SYNTHETIC = "synthetic_example"
DATA_BASIS_CONSENTED = "consented_customer"
DATA_BASIS_TEMPLATE = "blank_template"

STATUS_DRAFT = "draft"
STATUS_IN_REVIEW = "in_review"
STATUS_PUBLISHED = "published"

REVIEW_NONE = "none"
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_CHANGES = "changes_requested"

RESULT_QUOTE = "quote"
RESULT_NARRATIVE = "results_narrative"
METRIC_PREFIX = "metric:"


class CaseStudy(Base):
    """Structured case study following the standard template."""

    __tablename__ = "case_studies"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_case_studies_id_workspace"),
        Index("ix_case_studies_workspace_id", "workspace_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), nullable=False)
    company_name = Column(String(255), nullable=True)
    industry = Column(String(128), nullable=True)
    company_size = Column(String(64), nullable=True)
    challenge = Column(Text, nullable=True)
    solution = Column(Text, nullable=True)
    results = Column(Text, nullable=True)
    quote = Column(Text, nullable=True)
    quote_attribution = Column(String(255), nullable=True)
    metrics_json = Column(Text, nullable=True)
    quoted_organizations_json = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default=STATUS_DRAFT, server_default=STATUS_DRAFT)
    synthetic = Column(Boolean, nullable=False, default=False, server_default="false")
    data_basis = Column(
        String(32),
        nullable=False,
        default=DATA_BASIS_UNVERIFIED,
        server_default=DATA_BASIS_UNVERIFIED,
    )
    customer_claim = Column(Boolean, nullable=False, default=False, server_default="false")
    publication_authorized = Column(Boolean, nullable=False, default=False, server_default="false")
    review_status = Column(
        String(32), nullable=False, default=REVIEW_NONE, server_default=REVIEW_NONE
    )
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    schema_version = Column(
        String(32), nullable=False, default=SCHEMA_VERSION, server_default=SCHEMA_VERSION
    )
    reviewed_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    # Snapshot taken by revision tc25005_case_study_consent. Downgrade restores it
    # only while the row is still in the exact state that upgrade left.
    pre_consent_status = Column(String(32), nullable=True)
    pre_consent_published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CaseStudyOrganizationConsent(Base):
    """Consent from one quoted organization for one case study revision."""

    __tablename__ = "case_study_organization_consents"
    __table_args__ = (
        UniqueConstraint("id", "case_study_id", name="uq_case_study_consent_id_case"),
        ForeignKeyConstraint(
            ["case_study_id", "workspace_id"],
            ["case_studies.id", "case_studies.workspace_id"],
            ondelete="CASCADE",
            name="fk_case_study_consent_case_workspace",
        ),
        Index("ix_case_study_org_consent_workspace", "workspace_id"),
        Index("ix_case_study_org_consent_case", "case_study_id"),
        Index(
            "uq_case_study_org_consent_active",
            "case_study_id",
            "organization_name",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    case_study_id = Column(Integer, nullable=False)
    organization_name = Column(String(255), nullable=False)
    consent_reference = Column(String(255), nullable=True)
    consent_granted = Column(Boolean, nullable=False, default=True, server_default="true")
    granted_revision = Column(Integer, nullable=False)
    granted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class CaseStudyResultPermission(Base):
    """Permission, from one organization consent, to quote one result."""

    __tablename__ = "case_study_result_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_study_id", "workspace_id"],
            ["case_studies.id", "case_studies.workspace_id"],
            ondelete="CASCADE",
            name="fk_case_study_perm_case_workspace",
        ),
        ForeignKeyConstraint(
            ["consent_id", "case_study_id"],
            [
                "case_study_organization_consents.id",
                "case_study_organization_consents.case_study_id",
            ],
            ondelete="CASCADE",
            name="fk_case_study_perm_consent_case",
        ),
        Index("ix_case_study_result_perm_workspace", "workspace_id"),
        Index("ix_case_study_result_perm_case", "case_study_id"),
        Index("ix_case_study_result_perm_consent", "consent_id"),
        Index(
            "uq_case_study_result_perm_active",
            "consent_id",
            "result_key",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    case_study_id = Column(Integer, nullable=False)
    consent_id = Column(Integer, nullable=False)
    result_key = Column(String(128), nullable=False)
    permitted = Column(Boolean, nullable=False, default=True, server_default="true")
    granted_revision = Column(Integer, nullable=False)
    granted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)
