"""Executive dashboard service (P0-87) — combined platform health + business metrics."""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.credit_ledger import CreditLedger, CreditTransaction
from app.models.document import Document
from app.models.evidence_gap import EvidenceGap
from app.models.questionnaire import Question, Questionnaire
from app.models.subscription import Subscription
from app.models.workspace import Workspace


def get_executive_dashboard(db: Session) -> dict:
    """Generate the executive dashboard across all workspaces."""
    return {
        "platform": _platform_metrics(db),
        "revenue": _revenue_metrics(db),
        "content": _content_metrics(db),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _platform_metrics(db: Session) -> dict:
    workspaces = db.query(func.count(Workspace.id)).scalar() or 0
    return {
        "total_workspaces": workspaces,
        "total_documents": db.query(func.count(Document.id)).scalar() or 0,
        "total_questionnaires": db.query(func.count(Questionnaire.id)).scalar() or 0,
    }


def _revenue_metrics(db: Session) -> dict:
    active_subs = db.query(func.count(Subscription.id)).filter(
        Subscription.status.in_(["active", "trialing"])
    ).scalar() or 0
    total_credits_consumed = (
        db.query(func.coalesce(func.sum(CreditTransaction.amount), 0))
        .filter(CreditTransaction.kind == "consumption")
        .scalar() or 0
    )
    return {
        "active_subscriptions": active_subs,
        "total_credits_consumed": abs(total_credits_consumed),
    }


def _content_metrics(db: Session) -> dict:
    total_answers = db.query(func.count(Answer.id)).scalar() or 0
    total_questions = db.query(func.count(Question.id)).scalar() or 0
    gaps = db.query(func.count(EvidenceGap.id)).scalar() or 0
    return {
        "total_questions": total_questions,
        "total_answers": total_answers,
        "evidence_gaps": gaps,
        "coverage_pct": round(total_answers / total_questions * 100, 1) if total_questions else 0,
    }
