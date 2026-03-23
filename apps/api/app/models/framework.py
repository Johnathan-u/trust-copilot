"""Compliance frameworks (e.g. SOC2, ISO27001)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.core.database import Base


class Framework(Base):
    __tablename__ = "frameworks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    version = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
