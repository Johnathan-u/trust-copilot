"""Export schema (EXP-01)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text

from app.core.database import Base


class ExportRecord(Base):
    """Export artifact for history and download."""

    __tablename__ = "export_records"
    __table_args__ = (
        Index(
            "uq_export_records_job_id",
            "job_id",
            unique=True,
            postgresql_where=text("job_id IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    questionnaire_id = Column(
        Integer, ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True
    )
    storage_key = Column(String(512), nullable=False)
    filename = Column(String(255), nullable=False)
    status = Column(String(32), default="completed")
    # TC-10-003: the export job that produced this record (unique when set) so a retried job reuses it.
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
