"""Deal object model (E1-01). Anchors trust activity to revenue."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)

from app.core.database import Base

DEAL_STAGES = ("prospect", "discovery", "evaluation", "negotiation", "closed_won", "closed_lost")
DEAL_SCHEMA = "deals/v1"
CK_DEALS_STAGE = "ck_deals_stage"
CK_DEALS_CURRENCY = "ck_deals_currency"
STAGE_CHECK_SQL = "stage IN ('" + "', '".join(DEAL_STAGES) + "')"
CURRENCY_CHECK_SQL = "currency IS NULL OR currency ~ '^[A-Z]{3}$'"


class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint(STAGE_CHECK_SQL, name=CK_DEALS_STAGE),
        CheckConstraint(CURRENCY_CHECK_SQL, name=CK_DEALS_CURRENCY),
        # external_id is crm_external_id. Null connection, provider, or external id
        # stays out of the key so manual deals are not collapsed.
        Index(
            "uq_deals_ws_connection_provider_external",
            "workspace_id",
            "connection_id",
            "provider",
            "crm_external_id",
            unique=True,
            postgresql_where=text(
                "connection_id IS NOT NULL AND provider IS NOT NULL "
                "AND crm_external_id IS NOT NULL"
            ),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_name = Column(String(255), nullable=False)
    buyer_contact_name = Column(String(255), nullable=True)
    buyer_contact_email = Column(String(255), nullable=True)
    # Exact money. JSON responses use a decimal string, never a float.
    deal_value_arr = Column(Numeric(18, 2), nullable=True)
    currency = Column(String(3), nullable=True)
    stage = Column(String(32), nullable=False, default="prospect")
    close_date = Column(DateTime, nullable=True)
    expected_close_date = Column(Date, nullable=True)
    actual_close_date = Column(Date, nullable=True)
    requested_frameworks = Column(Text, nullable=True)  # JSON array
    linked_questionnaire_ids = Column(Text, nullable=True)  # JSON array
    linked_document_ids = Column(Text, nullable=True)  # JSON array
    room_id = Column(Integer, ForeignKey("shareable_spaces.id", ondelete="SET NULL"), nullable=True)
    crm_source = Column(String(32), nullable=True)  # salesforce, hubspot, manual
    crm_external_id = Column(String(255), nullable=True)
    connection_id = Column(
        Integer,
        ForeignKey(
            "crm_connections.id",
            ondelete="SET NULL",
            name="fk_deals_connection_id_crm_connections",
        ),
        nullable=True,
        index=True,
    )
    provider = Column(String(32), nullable=True)
    # Stable for one (workspace, connection, provider, external id). Not rewritten on retry.
    crm_stable_id = Column(String(512), nullable=True)
    crm_manual_fields = Column(Text, nullable=True)
    crm_removed_at = Column(DateTime, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
