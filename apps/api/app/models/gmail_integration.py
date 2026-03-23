"""Phase F: Per-workspace Gmail integration for evidence ingestion."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.database import Base


class GmailIntegration(Base):
    """Workspace Gmail connection: encrypted OAuth tokens, selected labels."""

    __tablename__ = "gmail_integrations"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=True)
    email_address = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GmailIngestLabel(Base):
    """Per-workspace approved Gmail label for evidence ingestion."""

    __tablename__ = "gmail_ingest_labels"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    gmail_integration_id = Column(Integer, ForeignKey("gmail_integrations.id", ondelete="CASCADE"), nullable=False)
    label_id = Column(String(255), nullable=False)
    label_name = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GmailControlSuggestion(Base):
    """Suggested control link for Gmail-ingested evidence. Requires manual approval."""

    __tablename__ = "gmail_control_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    control_id = Column(Integer, ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False)
    confidence = Column(Float, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
