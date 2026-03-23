"""Per-question structured LLM classification signals for the AI mapping pipeline."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base

MAPPING_QUALITY_VALUES = ("llm_structured", "llm_rerank", "heuristic_fallback")


class QuestionMappingSignal(Base):
    """Persisted LLM classification output per question: frameworks, subjects, raw JSON."""

    __tablename__ = "question_mapping_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=True, index=True)
    framework_labels_json = Column(Text, nullable=True)
    subject_labels_json = Column(Text, nullable=True)
    raw_llm_json = Column(Text, nullable=True)
    model = Column(String(64), nullable=True)
    prompt_version = Column(String(32), nullable=True)
    mapping_quality = Column(String(32), nullable=False, default="heuristic_fallback")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
