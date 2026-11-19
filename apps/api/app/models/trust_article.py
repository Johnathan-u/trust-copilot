"""Trust articles schema (TC-01)."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base


class TrustArticle(Base):
    """Security/compliance content for Trust Center."""

    __tablename__ = "trust_articles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_trust_articles_workspace_slug"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    slug = Column(String(128), nullable=False)
    category = Column(String(64), nullable=True)  # TC-R-B1: section for dashboard/public layout
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=True)
    published = Column(Integer, default=1)
    is_policy = Column(Boolean, default=False, nullable=False)  # TC-R-B5
    # Last approved version. Null until a deliberate publish. No FK: the version
    # row already references this article, and a second FK would cycle on delete.
    published_version_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TrustArticleVersion(Base):
    """Immutable snapshot of an approved trust article.

    Application code inserts a row and never updates it. The database rejects
    UPDATE as well. Delete happens only when the article itself is deleted.
    """

    __tablename__ = "trust_article_versions"
    __table_args__ = (
        UniqueConstraint(
            "trust_article_id",
            "version_number",
            name="uq_trust_article_versions_article_number",
        ),
        CheckConstraint("version_number >= 1", name="ck_trust_article_versions_number"),
    )

    id = Column(Integer, primary_key=True)
    trust_article_id = Column(
        Integer, ForeignKey("trust_articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number = Column(Integer, nullable=False)
    slug = Column(String(128), nullable=False)
    category = Column(String(64), nullable=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    is_policy = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
