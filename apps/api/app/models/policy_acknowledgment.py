"""Policy acknowledgment tracking (TC-R-B5)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer

from app.core.database import Base


class PolicyAcknowledgment(Base):
    """User acknowledged a policy (trust article marked as policy)."""

    __tablename__ = "policy_acknowledgments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trust_article_id = Column(Integer, ForeignKey("trust_articles.id", ondelete="CASCADE"), nullable=False, index=True)
    acknowledged_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
