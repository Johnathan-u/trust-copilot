"""Policy acknowledgment tracking (TC-R-B5)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint

from app.core.database import Base


class PolicyAcknowledgment(Base):
    """User acknowledged one published policy version in one workspace.

    ``revoked_at`` is set when that version is unpublished or replaced. A later
    acknowledgment of a new version is a new row. The same version is one row.
    """

    __tablename__ = "policy_acknowledgments"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "article_version_id",
            name="uq_policy_ack_user_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trust_article_id = Column(
        Integer, ForeignKey("trust_articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_version_id = Column(
        Integer,
        ForeignKey(
            "trust_article_versions.id",
            name="fk_policy_ack_version",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", name="fk_policy_ack_workspace", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    acknowledged_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
