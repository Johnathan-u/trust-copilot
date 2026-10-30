"""Security FAQ content, review provenance and bounded version history."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)

from app.core.database import Base


class SecurityFAQ(Base):
    __tablename__ = "security_faq"
    __table_args__ = (
        CheckConstraint("revision IS NULL OR revision >= 1", name="ck_security_faq_revision"),
        CheckConstraint(
            "publication_state IS NULL OR publication_state IN ('draft','approved','published','withdrawn')",
            name="ck_security_faq_publication_state",
        ),
        CheckConstraint(
            "char_length(question) <= 2000 AND char_length(answer) <= 20000",
            name="ck_security_faq_content_bounds",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    framework_tags = Column(String(512), nullable=True)
    is_default = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # NULL values deliberately preserve the lack of provenance on pre-review rows.
    revision = Column(Integer, nullable=True)
    publication_state = Column(String(16), nullable=True)
    synthetic = Column(Boolean, nullable=True)
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", name="fk_security_faq_reviewer", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_revision = Column(Integer, nullable=True)
    reviewed_evidence_digest = Column(String(64), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_revision = Column(Integer, nullable=True)


class SecurityFAQSource(Base):
    __tablename__ = "security_faq_sources"
    faq_id = Column(Integer, ForeignKey("security_faq.id", ondelete="CASCADE"), primary_key=True)
    evidence_item_id = Column(
        Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class SecurityFAQRevision(Base):
    __tablename__ = "security_faq_revisions"
    __table_args__ = (CheckConstraint("revision >= 1", name="ck_security_faq_history_revision"),)
    faq_id = Column(Integer, ForeignKey("security_faq.id", ondelete="CASCADE"), primary_key=True)
    revision = Column(Integer, primary_key=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category = Column(String(64), nullable=False)
    question = Column(String(2000), nullable=False)
    answer = Column(String(20000), nullable=False)
    framework_tags = Column(String(512), nullable=True)
    source_evidence_ids_json = Column(String(512), nullable=False)
    synthetic = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
