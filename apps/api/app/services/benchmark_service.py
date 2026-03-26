"""Benchmark dashboard service (P0-84) — turnaround, coverage, reuse metrics."""

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.document import Document
from app.models.evidence_gap import EvidenceGap
from app.models.export_record import ExportRecord
from app.models.job import Job
from app.models.questionnaire import Question, Questionnaire
from app.models.workspace_ai_usage import WorkspaceAIUsage

logger = logging.getLogger(__name__)


def get_benchmarks(db: Session, workspace_id: int) -> dict:
    """Generate benchmark dashboard data for a workspace."""
    return {
        "questionnaire_metrics": _questionnaire_metrics(db, workspace_id),
        "answer_metrics": _answer_metrics(db, workspace_id),
        "evidence_metrics": _evidence_metrics(db, workspace_id),
        "ai_usage": _ai_usage(db, workspace_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _questionnaire_metrics(db: Session, workspace_id: int) -> dict:
    total = db.query(Questionnaire).filter(Questionnaire.workspace_id == workspace_id).count()
    parsed = db.query(Questionnaire).filter(
        Questionnaire.workspace_id == workspace_id,
        Questionnaire.status == "parsed",
    ).count()
    exports = db.query(ExportRecord).filter(ExportRecord.workspace_id == workspace_id).count()

    jobs = db.query(Job).filter(
        Job.workspace_id == workspace_id,
        Job.kind.in_(["generate-answers", "export"]),
    ).all()

    turnaround_seconds = []
    for j in jobs:
        if j.started_at and j.completed_at:
            delta = (j.completed_at - j.started_at).total_seconds()
            if delta > 0:
                turnaround_seconds.append(delta)

    avg_turnaround = round(sum(turnaround_seconds) / len(turnaround_seconds), 1) if turnaround_seconds else 0

    return {
        "total_questionnaires": total,
        "parsed": parsed,
        "exports_generated": exports,
        "avg_job_turnaround_seconds": avg_turnaround,
        "total_jobs": len(jobs),
    }


def _answer_metrics(db: Session, workspace_id: int) -> dict:
    total_answers = (
        db.query(Answer)
        .join(Question)
        .join(Questionnaire)
        .filter(Questionnaire.workspace_id == workspace_id)
        .count()
    )
    total_questions = (
        db.query(Question)
        .join(Questionnaire)
        .filter(Questionnaire.workspace_id == workspace_id)
        .count()
    )

    approved = (
        db.query(Answer)
        .join(Question)
        .join(Questionnaire)
        .filter(Questionnaire.workspace_id == workspace_id, Answer.status == "approved")
        .count()
    )

    confidences = (
        db.query(Answer.confidence)
        .join(Question)
        .join(Questionnaire)
        .filter(Questionnaire.workspace_id == workspace_id, Answer.confidence.isnot(None))
        .all()
    )
    conf_values = [c[0] for c in confidences]
    avg_conf = round(sum(conf_values) / len(conf_values), 1) if conf_values else 0
    coverage_pct = round(total_answers / total_questions * 100, 1) if total_questions else 0

    return {
        "total_questions": total_questions,
        "total_answers": total_answers,
        "approved_answers": approved,
        "coverage_pct": coverage_pct,
        "avg_confidence": avg_conf,
        "approval_rate": round(approved / total_answers * 100, 1) if total_answers else 0,
    }


def _evidence_metrics(db: Session, workspace_id: int) -> dict:
    docs = db.query(Document).filter(Document.workspace_id == workspace_id).count()
    gaps = db.query(EvidenceGap).filter(EvidenceGap.workspace_id == workspace_id).count()
    return {"total_documents": docs, "evidence_gaps": gaps}


def _ai_usage(db: Session, workspace_id: int) -> dict:
    rows = (
        db.query(WorkspaceAIUsage)
        .filter(WorkspaceAIUsage.workspace_id == workspace_id)
        .order_by(WorkspaceAIUsage.period.desc())
        .limit(6)
        .all()
    )
    return {
        "periods": [
            {
                "period": r.period,
                "llm_calls": r.llm_calls,
                "tokens_used": r.tokens_used,
                "answer_calls": r.answer_calls,
            }
            for r in rows
        ],
    }
