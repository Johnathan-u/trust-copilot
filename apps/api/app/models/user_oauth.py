"""OAuth account linking (ENT-201)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.core.database import Base


class UserOAuthAccount(Base):
    """Links a provider identity (Google, Microsoft) to a User."""

    __tablename__ = "user_oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False, index=True)  # google, microsoft
    provider_user_id = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=True)  # from provider at link time
    created_at = Column(DateTime, default=datetime.utcnow)
