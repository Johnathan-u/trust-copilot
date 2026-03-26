"""Customer-ready export pack — branded cover, executive summary, evidence bundle."""

import logging
from datetime import datetime, timezone
from io import BytesIO

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.document import Document
from app.models.evidence_gap import EvidenceGap
from app.models.questionnaire import Question, Questionnaire
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


def generate_cover_page(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
) -> dict:
    """Generate data for a branded cover page."""
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.workspace_id == workspace_id,
    ).first()

    if not qnr:
        raise ValueError("Questionnaire not found")

    q_count = db.query(Question).filter(Question.questionnaire_id == questionnaire_id).count()
    a_count = (
        db.query(Answer)
        .join(Question)
        .filter(Question.questionnaire_id == questionnaire_id)
        .count()
    )

    return {
        "workspace_name": ws.name if ws else "Trust Copilot",
        "questionnaire_title": qnr.filename or f"Questionnaire #{qnr.id}",
        "generated_date": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        "total_questions": q_count,
        "total_answers": a_count,
        "completion_pct": round(a_count / q_count * 100, 1) if q_count else 0,
        "powered_by": "Trust Copilot — Compliance questionnaires, answered with evidence",
        "confidentiality_notice": (
            "CONFIDENTIAL — This document contains proprietary information prepared "
            "for the exclusive use of the intended recipient. Do not distribute, "
            "copy, or disclose without prior authorization."
        ),
    }


def generate_executive_summary(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
) -> dict:
    """Generate an executive summary for the completed questionnaire."""
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.workspace_id == workspace_id,
    ).first()
    if not qnr:
        raise ValueError("Questionnaire not found")

    questions = db.query(Question).filter(Question.questionnaire_id == questionnaire_id).all()
    q_ids = [q.id for q in questions]

    answers = []
    if q_ids:
        answers = db.query(Answer).filter(Answer.question_id.in_(q_ids)).all()

    total_q = len(questions)
    total_a = len(answers)
    confidences = [a.confidence for a in answers if a.confidence is not None]
    avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0
    high = sum(1 for c in confidences if c >= 90)
    med = sum(1 for c in confidences if 70 <= c < 90)
    low = sum(1 for c in confidences if c < 70)

    sections = {}
    for q in questions:
        sec = q.section or "General"
        if sec not in sections:
            sections[sec] = 0
        sections[sec] += 1

    return {
        "questionnaire": qnr.filename or f"Questionnaire #{qnr.id}",
        "framework_detected": qnr.framework if hasattr(qnr, "framework") and qnr.framework else "General",
        "total_questions": total_q,
        "total_answers": total_a,
        "completion_rate": round(total_a / total_q * 100, 1) if total_q else 0,
        "average_confidence": avg_confidence,
        "confidence_distribution": {
            "high_90_plus": high,
            "medium_70_89": med,
            "low_below_70": low,
        },
        "sections_covered": len(sections),
        "section_breakdown": [{"name": k, "questions": v} for k, v in sections.items()],
        "methodology": (
            "Answers were generated using Trust Copilot's RAG (Retrieval-Augmented Generation) pipeline. "
            "Each answer is backed by evidence retrieved from the organization's uploaded compliance documents, "
            "policies, and certifications. Confidence scores reflect the strength and relevance of available evidence."
        ),
        "recommendation": _summary_recommendation(avg_confidence, total_a, total_q),
    }


def generate_evidence_bundle(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
) -> dict:
    """Generate an evidence bundle manifest listing all documents referenced."""
    questions = db.query(Question).filter(Question.questionnaire_id == questionnaire_id).all()
    q_ids = [q.id for q in questions]

    answers = []
    if q_ids:
        answers = db.query(Answer).filter(Answer.question_id.in_(q_ids)).all()

    doc_ids = set()
    cited_sources = []
    for a in answers:
        if a.citations:
            try:
                import json
                cites = json.loads(a.citations) if isinstance(a.citations, str) else a.citations
                if isinstance(cites, list):
                    for cite in cites:
                        if isinstance(cite, dict):
                            did = cite.get("document_id")
                            if did:
                                doc_ids.add(did)
                            cited_sources.append({
                                "question_id": a.question_id,
                                "document_id": did,
                                "chunk_text": cite.get("text", "")[:200],
                            })
            except Exception:
                pass

    documents = []
    if doc_ids:
        docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
        for d in docs:
            documents.append({
                "id": d.id,
                "filename": d.filename,
                "upload_date": d.created_at.isoformat() if d.created_at else None,
            })

    gaps = (
        db.query(EvidenceGap)
        .filter(EvidenceGap.workspace_id == workspace_id)
        .limit(20)
        .all()
    )
    gap_list = [
        {
            "control_area": g.control_area if hasattr(g, "control_area") else None,
            "description": g.description if hasattr(g, "description") else str(g.gap_type) if hasattr(g, "gap_type") else "Evidence gap",
            "status": g.status if hasattr(g, "status") else "open",
        }
        for g in gaps
    ]

    return {
        "total_documents_cited": len(doc_ids),
        "documents": documents,
        "total_citations": len(cited_sources),
        "evidence_gaps": gap_list,
        "bundle_generated_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_full_pack(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
) -> dict:
    """Generate the complete customer-ready export pack."""
    return {
        "cover_page": generate_cover_page(db, workspace_id, questionnaire_id),
        "executive_summary": generate_executive_summary(db, workspace_id, questionnaire_id),
        "evidence_bundle": generate_evidence_bundle(db, workspace_id, questionnaire_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _summary_recommendation(avg_conf: float, answered: int, total: int) -> str:
    completion = answered / total * 100 if total else 0
    if completion >= 95 and avg_conf >= 90:
        return "All questions are answered with high confidence. This questionnaire is ready for submission."
    if completion >= 80 and avg_conf >= 75:
        return "Most questions are answered with good confidence. Review low-confidence answers before submission."
    if completion >= 50:
        return "Additional evidence documents should be uploaded to improve answer coverage and confidence."
    return "Significant gaps remain. Upload additional compliance documents and policies to improve coverage."
