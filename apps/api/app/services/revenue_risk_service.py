"""Revenue-at-risk scoring (E1-04).

For each deal, compute a trust risk score based on unanswered questions,
low-confidence answers, stale evidence, unapproved answers, and unresolved gaps.
"""

import json
import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.deal import Deal
from app.models.evidence_item import EvidenceItem
from app.models.golden_answer import GoldenAnswer  # noqa: F401
from app.models.questionnaire import Question, Questionnaire
from app.services.deal_service import money_text

logger = logging.getLogger(__name__)


def score_deal(db: Session, deal_id: int, *, workspace_id: int) -> dict:
    deal = db.query(Deal).filter(Deal.id == deal_id, Deal.workspace_id == workspace_id).first()
    if not deal:
        return {"error": "Deal not found"}

    linked = json.loads(deal.linked_questionnaire_ids or "[]")
    # Only questionnaires from the deal's own workspace (legacy links may point elsewhere).
    q_ids = (
        [
            row.id
            for row in db.query(Questionnaire.id).filter(
                Questionnaire.id.in_(linked),
                Questionnaire.workspace_id == deal.workspace_id,
                Questionnaire.deleted_at.is_(None),
            )
        ]
        if linked
        else []
    )
    total_questions = 0
    unanswered = 0
    low_confidence = 0
    unapproved = 0

    for qid in q_ids:
        questions = db.query(Question).filter(Question.questionnaire_id == qid).all()
        total_questions += len(questions)
        for q in questions:
            answer = (
                db.query(Answer)
                .filter(Answer.question_id == q.id)
                .order_by(Answer.created_at.desc())
                .first()
            )
            if not answer or not answer.text:
                unanswered += 1
            elif answer.confidence and answer.confidence < 50:
                low_confidence += 1
            elif answer.status in ("draft", "flagged"):
                unapproved += 1

    stale_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.workspace_id == deal.workspace_id,
            EvidenceItem.approval_status == "rejected",
        )
        .count()
    )

    risk_factors = unanswered * 3 + low_confidence * 2 + unapproved * 1 + stale_evidence * 2
    deal_value = None if deal.deal_value_arr is None else Decimal(deal.deal_value_arr)
    if deal_value is None:
        risk_amount = None
    elif total_questions:
        ratio = min(Decimal(risk_factors) / Decimal(total_questions), Decimal(1))
        risk_amount = (deal_value * ratio).quantize(Decimal("0.01"))
    else:
        risk_amount = Decimal("0.00")

    return {
        "deal_id": deal.id,
        "company_name": deal.company_name,
        "deal_value_arr": money_text(deal_value),
        "stage": deal.stage,
        "risk_score": risk_factors,
        "revenue_at_risk": money_text(risk_amount),
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
    scored = [score_deal(db, d.id, workspace_id=workspace_id) for d in deals]
    scored = [row for row in scored if "error" not in row]
    scored.sort(key=_risk_sort_key)
    return scored


def _risk_sort_key(row: dict) -> tuple[bool, Decimal]:
    raw = row.get("revenue_at_risk")
    if raw is None:
        return (True, Decimal("0"))
    return (False, -Decimal(raw))
