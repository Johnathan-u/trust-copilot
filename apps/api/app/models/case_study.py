"""Case study template model (P0-83)."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class CaseStudy(Base):
    """Structured case study following the standard template."""

    __tablename__ = "case_studies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
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
    status = Column(String(32), nullable=False, default="draft")
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
