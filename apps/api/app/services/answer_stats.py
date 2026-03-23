"""Answer outcome analytics: per-questionnaire stats and category-level gap aggregation."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Answer, Question, Questionnaire


def get_questionnaire_answer_stats(db: Session, workspace_id: int, questionnaire_id: int) -> dict:
    """Breakdown of answer statuses for one questionnaire + category rollup."""
    qnr = (
        db.query(Questionnaire)
        .filter(Questionnaire.id == questionnaire_id, Questionnaire.workspace_id == workspace_id)
        .first()
    )
    if not qnr:
        return {"error": "not_found"}

    rows = (
        db.query(Answer.status, Answer.insufficient_reason, Answer.gating_reason, Answer.primary_categories_json)
        .join(Question, Question.id == Answer.question_id)
        .filter(Question.questionnaire_id == questionnaire_id)
        .all()
    )

    total_questions = (
        db.query(func.count(Question.id))
        .filter(Question.questionnaire_id == questionnaire_id)
        .scalar() or 0
    )

    status_counts: Counter[str] = Counter()
    gating_counts: Counter[str] = Counter()
    insufficient_counts: Counter[str] = Counter()
    category_gaps: Counter[str] = Counter()

    for status, insuf_reason, gating_reason, cat_json in rows:
        status_counts[status or "unknown"] += 1
        if gating_reason:
            gating_counts[gating_reason] += 1
        if insuf_reason:
            insufficient_counts[insuf_reason] += 1
        if status in ("insufficient_evidence",) and cat_json:
            try:
                cats = json.loads(cat_json)
                for s in cats.get("subjects") or []:
                    category_gaps[s] += 1
                for f in cats.get("frameworks") or []:
                    category_gaps[f"fw:{f}"] += 1
            except Exception:
                pass

    answered = status_counts.get("draft", 0) + status_counts.get("approved", 0)
    not_answered = total_questions - answered

    return {
        "questionnaire_id": questionnaire_id,
        "total_questions": total_questions,
        "total_answers": sum(status_counts.values()),
        "answered": answered,
        "not_answered": not_answered,
        "status_breakdown": dict(status_counts.most_common()),
        "gating_breakdown": dict(gating_counts.most_common()),
        "insufficient_breakdown": dict(insufficient_counts.most_common()),
        "category_gaps": dict(category_gaps.most_common(30)),
    }


def get_workspace_gap_analytics(
    db: Session,
    workspace_id: int,
    *,
    group_by: str = "subject",
) -> dict:
    """Aggregate insufficient answers across all workspace questionnaires by category.

    group_by: 'subject' (default) or 'framework'.
    Returns list of {label, count} sorted descending for chart display.
    """
    rows = (
        db.query(Answer.primary_categories_json, Answer.status, Answer.insufficient_reason)
        .join(Question, Question.id == Answer.question_id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
            Answer.status == "insufficient_evidence",
        )
        .all()
    )

    counts: Counter[str] = Counter()
    total_insufficient = 0

    for cat_json, status, insuf_reason in rows:
        total_insufficient += 1
        if not cat_json:
            counts["Uncategorized"] += 1
            continue
        try:
            cats = json.loads(cat_json)
        except Exception:
            counts["Uncategorized"] += 1
            continue

        if group_by == "framework":
            labels = cats.get("frameworks") or []
        else:
            labels = cats.get("subjects") or []
        if not labels:
            counts["Uncategorized"] += 1
        for lbl in labels:
            counts[lbl] += 1

    items = [{"label": k, "count": v} for k, v in counts.most_common(50)]

    total_answers = (
        db.query(func.count(Answer.id))
        .join(Question, Question.id == Answer.question_id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .scalar() or 0
    )

    return {
        "group_by": group_by,
        "total_answers": total_answers,
        "total_insufficient": total_insufficient,
        "items": items,
    }
