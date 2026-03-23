"""Questionnaire model (QNR-01)."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


def _utc_now():
    return datetime.now(timezone.utc)


class Questionnaire(Base):
    """Uploaded questionnaire file and parse metadata."""

    __tablename__ = "questionnaires"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    storage_key = Column(String(512), nullable=True)
    filename = Column(String(255), nullable=False)
    display_id = Column(String(32), nullable=True, index=True)
    frameworks_json = Column(Text, nullable=True)
    subject_areas_json = Column(Text, nullable=True)
    status = Column(String(32), default="uploaded")
    parse_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Legacy: framework bias (unused by new pipeline; prefer mapping_preferred_subject_areas_json)
    mapping_preferred_framework = Column(String(32), nullable=True)
    # JSON list of subject-area labels (e.g. ["Access Control","Encryption"]) for AI category mapping
    mapping_preferred_subject_areas_json = Column(Text, nullable=True)
    # JSON array of document IDs (workspace evidence) the AI may use when drafting answers; NULL/[] = no restriction
    answer_evidence_document_ids_json = Column(Text, nullable=True)


class Question(Base):
    """Parsed question from a questionnaire."""

    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    section = Column(String(255), nullable=True)
    answer_type = Column(String(64), nullable=True)
    source_location = Column(Text, nullable=True)
    confidence = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utc_now)
