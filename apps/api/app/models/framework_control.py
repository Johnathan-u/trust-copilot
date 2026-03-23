"""Framework control templates (e.g. CC6.1, A.9.2.1)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class FrameworkControl(Base):
    __tablename__ = "framework_controls"

    id = Column(Integer, primary_key=True, index=True)
    framework_id = Column(Integer, ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False, index=True)
    control_key = Column(String(64), nullable=False)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    category = Column(String(64), nullable=True)
    criticality = Column(String(16), nullable=False, default="medium")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
