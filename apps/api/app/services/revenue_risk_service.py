"""Revenue-at-risk scoring (E1-04).

For each deal, compute a trust risk score based on unanswered questions,
low-confidence answers, stale evidence, unapproved answers, and unresolved gaps.
"""

import json
import logging

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.deal import Deal
from app.models.evidence_item import EvidenceItem
from app.models.golden_answer import GoldenAnswer
from app.models.questionnaire import Question, Questionnaire

logger = logging.getLogger(__name__)


def score_deal(db: Session, deal_id: int) -> dict:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        return {"error": "Deal not found"}

    q_ids = json.loads(deal.linked_questionnaire_ids or "[]")
    total_questions = 0
    unanswered = 0
    low_confidence = 0
    unapproved = 0

    for qid in q_ids:
        questions = db.query(Question).filter(Question.questionnaire_id == qid).all()
        total_questions += len(questions)
        for q in questions:
            answer = db.query(Answer).filter(Answer.question_id == q.id).order_by(Answer.created_at.desc()).first()
            if not answer or not answer.text:
                unanswered += 1
            elif answer.confidence and answer.confidence < 50:
                low_confidence += 1
            elif answer.status in ("draft", "flagged"):
                unapproved += 1

    stale_evidence = db.query(EvidenceItem).filter(
        EvidenceItem.workspace_id == deal.workspace_id,
        EvidenceItem.approval_status == "rejected",
    ).count()

    risk_factors = unanswered * 3 + low_confidence * 2 + unapproved * 1 + stale_evidence * 2
    deal_value = deal.deal_value_arr or 0
    risk_amount = round(deal_value * min(risk_factors / max(total_questions, 1), 1.0), 2) if total_questions else 0

    return {
        "deal_id": deal.id,
        "company_name": deal.company_name,
        "deal_value_arr": deal_value,
        "stage": deal.stage,
        "risk_score": risk_factors,
        "revenue_at_risk": risk_amount,
        "breakdown": {
            "unanswered_questions": unanswered,
            "low_confidence_answers": low_confidence,
            "unapproved_answers": unapproved,
            "stale_evidence": stale_evidence,
            "total_questions": total_questions,
        },
    }


def rank_deals_by_risk(db: Session, workspace_id: int) -> list[dict]:
    deals = db.query(Deal).filter(Deal.workspace_id == workspace_id).all()
    scored = [score_deal(db, d.id) for d in deals]
    scored = [s for s in scored if "error" not in s]
    scored.sort(key=lambda s: s["revenue_at_risk"], reverse=True)
    return scored
