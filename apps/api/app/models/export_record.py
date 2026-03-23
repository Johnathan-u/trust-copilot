"""Export schema (EXP-01)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class ExportRecord(Base):
    """Export artifact for history and download."""

    __tablename__ = "export_records"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True)
    storage_key = Column(String(512), nullable=False)
    filename = Column(String(255), nullable=False)
    status = Column(String(32), default="completed")
    created_at = Column(DateTime, default=datetime.utcnow)
