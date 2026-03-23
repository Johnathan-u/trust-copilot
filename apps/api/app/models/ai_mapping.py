"""AI Mapping & Governance models for admin-managed retrieval tuning."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.core.database import Base

MAPPING_SOURCES = ("system", "ai", "manual")


class FrameworkControlMapping(Base):
    __tablename__ = "framework_control_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    framework_key = Column(String(128), nullable=False)
    control_id = Column(Integer, ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(16), nullable=False, default="manual")
    confidence = Column(Float, nullable=True)
    approved = Column(Boolean, nullable=False, default=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("workspace_id", "framework_key", "control_id", name="uq_fcm_ws_fk_ctrl"),
    )


class ControlEvidenceMapping(Base):
    __tablename__ = "control_evidence_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    control_id = Column(Integer, ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(16), nullable=False, default="manual")
    confidence = Column(Float, nullable=True)
    approved = Column(Boolean, nullable=False, default=False)
    override_priority = Column(Integer, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("workspace_id", "control_id", "evidence_id", name="uq_cem_ws_ctrl_ev"),
    )


class EvidenceTagMapping(Base):
    __tablename__ = "evidence_tag_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(16), nullable=False, default="manual")
    confidence = Column(Float, nullable=True)
    approved = Column(Boolean, nullable=False, default=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("workspace_id", "evidence_id", "tag_id", name="uq_etm_ws_ev_tag"),
    )


MAPPING_STATUSES = ("suggested", "approved", "rejected", "manual")


class QuestionMappingPreference(Base):
    __tablename__ = "question_mapping_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=True, index=True)
    normalized_question_text = Column(Text, nullable=True)
    preferred_control_id = Column(Integer, ForeignKey("workspace_controls.id", ondelete="SET NULL"), nullable=True)
    preferred_tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)
    preferred_framework_key = Column(String(128), nullable=True)
    weight = Column(Float, nullable=True)
    source = Column(String(16), nullable=False, default="manual")
    confidence = Column(Float, nullable=True)
    approved = Column(Boolean, nullable=False, default=False)
    status = Column(String(32), nullable=False, default="suggested")
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())


class AIGovernanceSettings(Base):
    __tablename__ = "ai_governance_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    require_approved_mappings = Column(Boolean, nullable=False, default=False)
    require_approved_ai_tags = Column(Boolean, nullable=False, default=False)
    minimum_ai_mapping_confidence = Column(Float, nullable=True)
    minimum_ai_tag_confidence = Column(Float, nullable=True)
    manual_mapping_boost = Column(Float, nullable=False, default=0.05)
    approved_mapping_boost = Column(Float, nullable=False, default=0.04)
    approved_tag_boost = Column(Float, nullable=False, default=0.03)
    control_match_boost = Column(Float, nullable=False, default=0.04)
    framework_match_boost = Column(Float, nullable=False, default=0.03)
    allow_ai_unapproved_for_retrieval = Column(Boolean, nullable=False, default=True)
    allow_manual_overrides = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())
