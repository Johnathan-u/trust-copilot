"""Customer-specific knowledge packs service (P1-59)."""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.document import Document
from app.models.questionnaire import Question, Questionnaire


def generate_knowledge_pack(db: Session, workspace_id: int, questionnaire_id: int | None = None) -> dict:
    """Generate a customer-specific knowledge pack from workspace answers and documents."""
    q_filter = [Questionnaire.workspace_id == workspace_id]
    if questionnaire_id:
        q_filter.append(Questionnaire.id == questionnaire_id)

    questionnaires = db.query(Questionnaire).filter(*q_filter).all()

    answers_by_category: dict[str, list] = {}
    for qnr in questionnaires:
        questions = db.query(Question).filter(Question.questionnaire_id == qnr.id).all()
        for question in questions:
            answer = db.query(Answer).filter(Answer.question_id == question.id).first()
            if not answer or not answer.text:
                continue

            category = _categorize_question(question.text)
            if category not in answers_by_category:
                answers_by_category[category] = []
            answers_by_category[category].append({
                "question": question.text,
                "answer": answer.text,
                "confidence": answer.confidence,
                "status": answer.status,
                "source_questionnaire": qnr.filename,
            })

    docs = db.query(Document).filter(Document.workspace_id == workspace_id).all()
    supporting_docs = [
        {"id": d.id, "filename": d.filename}
        for d in docs[:20]
    ]

    return {
        "workspace_id": workspace_id,
        "categories": [
            {"name": cat, "answers": items}
            for cat, items in sorted(answers_by_category.items())
        ],
        "total_answers": sum(len(v) for v in answers_by_category.values()),
        "total_categories": len(answers_by_category),
        "supporting_documents": supporting_docs,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _categorize_question(text: str) -> str:
    text_lower = text.lower()
    categories = {
        "Access Control": ["access control", "authentication", "authorization", "mfa", "multi-factor", "sso", "single sign"],
        "Data Protection": ["encryption", "data protection", "data at rest", "data in transit", "data loss", "dlp"],
        "Incident Response": ["incident", "breach", "disaster recovery", "business continuity"],
        "Network Security": ["network", "firewall", "vpn", "intrusion", "ids", "ips"],
        "Compliance": ["compliance", "audit", "regulation", "gdpr", "soc 2", "hipaa", "iso 27001", "pci"],
        "Change Management": ["change management", "deployment", "release", "ci/cd", "version control"],
        "Vendor Management": ["vendor", "third party", "subprocessor", "supply chain"],
        "Data Retention": ["retention", "deletion", "disposal", "archiving", "backup"],
        "Physical Security": ["physical", "data center", "facility", "badge"],
        "HR Security": ["background check", "training", "awareness", "onboarding", "offboarding"],
    }
    for cat, keywords in categories.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return "General"
