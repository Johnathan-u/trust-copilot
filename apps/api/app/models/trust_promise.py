"""Trust promise and contract document models (E2-08, E2-09)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

PROMISE_SOURCE_TYPES = (
    "questionnaire_answer",
    "trust_article",
    "contract_clause",
    "sla",
    "security_addendum",
    "verbal",
    "sales_commitment",
)
PROMISE_STATUSES = ("active", "expired", "contradicted", "fulfilled", "superseded")


class ContractDocument(Base):
    __tablename__ = "contract_documents"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=True)
    clauses_json = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="ready")
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TrustPromise(Base):
    __tablename__ = "trust_promises"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    promise_text = Column(Text, nullable=False)
    source_type = Column(String(64), nullable=False)
    source_ref_id = Column(Integer, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    review_at = Column(DateTime, nullable=True)
    control_ids_json = Column(Text, nullable=True)
    evidence_ids_json = Column(Text, nullable=True)
    deal_id = Column(Integer, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    contract_document_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True)
    topic_key = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
