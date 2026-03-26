"""Deal room service (E1-05).

Auto-generates a packaged workspace for each deal with questionnaire answers,
Trust Center articles, evidence documents, and status dashboard.
"""

import json
import logging
import secrets

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.deal import Deal
from app.models.questionnaire import Question, Questionnaire
from app.models.trust_article import TrustArticle

logger = logging.getLogger(__name__)


def generate_deal_room(db: Session, deal_id: int) -> dict:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        return {"error": "Deal not found"}

    q_ids = json.loads(deal.linked_questionnaire_ids or "[]")
    questionnaire_data = []
    for qid in q_ids:
        questionnaire = db.query(Questionnaire).filter(Questionnaire.id == qid).first()
        if not questionnaire:
            continue
        questions = db.query(Question).filter(Question.questionnaire_id == qid).all()
        q_list = []
        proven = 0
        pending = 0
        for q in questions:
            answer = db.query(Answer).filter(Answer.question_id == q.id).order_by(Answer.created_at.desc()).first()
            status = "pending"
            if answer and answer.status == "approved":
                status = "proven"
                proven += 1
            elif answer and answer.text:
                status = "draft"
                pending += 1
            else:
                pending += 1
            q_list.append({
                "question_id": q.id,
                "text": q.text,
                "answer_status": status,
                "answer_text": answer.text[:200] if answer and answer.text else None,
            })
        questionnaire_data.append({
            "questionnaire_id": qid,
            "name": questionnaire.name,
            "proven": proven,
            "pending": pending,
            "total": len(questions),
            "questions": q_list,
        })

    articles = db.query(TrustArticle).filter(
        TrustArticle.workspace_id == deal.workspace_id,
        TrustArticle.published == 1,
    ).all()
    article_data = [{"id": a.id, "title": a.title, "slug": a.slug} for a in articles]

    access_token = secrets.token_urlsafe(32)

    return {
        "deal_id": deal.id,
        "company_name": deal.company_name,
        "stage": deal.stage,
        "access_token": access_token,
        "questionnaires": questionnaire_data,
        "trust_center_articles": article_data,
        "summary": {
            "total_questionnaires": len(questionnaire_data),
            "total_articles": len(article_data),
        },
    }
