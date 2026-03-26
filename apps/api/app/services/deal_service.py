"""Deal management service (E1-01)."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.deal import Deal

logger = logging.getLogger(__name__)


def create_deal(db: Session, workspace_id: int, company_name: str, **kwargs) -> dict:
    deal = Deal(workspace_id=workspace_id, company_name=company_name, **kwargs)
    if "requested_frameworks" in kwargs and isinstance(kwargs["requested_frameworks"], list):
        deal.requested_frameworks = json.dumps(kwargs["requested_frameworks"])
    if "linked_questionnaire_ids" in kwargs and isinstance(kwargs["linked_questionnaire_ids"], list):
        deal.linked_questionnaire_ids = json.dumps(kwargs["linked_questionnaire_ids"])
    db.add(deal)
    db.flush()
    return _serialize(deal)


def get_deal(db: Session, deal_id: int) -> dict | None:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    return _serialize(deal) if deal else None


def list_deals(db: Session, workspace_id: int, stage: str | None = None) -> list[dict]:
    q = db.query(Deal).filter(Deal.workspace_id == workspace_id)
    if stage:
        q = q.filter(Deal.stage == stage)
    return [_serialize(d) for d in q.order_by(Deal.created_at.desc()).all()]


def update_deal(db: Session, deal_id: int, **updates) -> dict | None:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        return None
    allowed = {"company_name", "buyer_contact_name", "buyer_contact_email", "deal_value_arr",
               "stage", "close_date", "notes", "owner_user_id", "crm_source", "crm_external_id"}
    for k, v in updates.items():
        if k in allowed:
            setattr(deal, k, v)
    if "requested_frameworks" in updates:
        val = updates["requested_frameworks"]
        deal.requested_frameworks = json.dumps(val) if isinstance(val, list) else val
    if "linked_questionnaire_ids" in updates:
        val = updates["linked_questionnaire_ids"]
        deal.linked_questionnaire_ids = json.dumps(val) if isinstance(val, list) else val
    db.flush()
    return _serialize(deal)


def delete_deal(db: Session, deal_id: int) -> bool:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        return False
    db.delete(deal)
    db.flush()
    return True


def link_questionnaire(db: Session, deal_id: int, questionnaire_id: int) -> dict | None:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        return None
    ids = json.loads(deal.linked_questionnaire_ids or "[]")
    if questionnaire_id not in ids:
        ids.append(questionnaire_id)
        deal.linked_questionnaire_ids = json.dumps(ids)
        db.flush()
    return _serialize(deal)


def _serialize(deal: Deal) -> dict:
    return {
        "id": deal.id,
        "workspace_id": deal.workspace_id,
        "company_name": deal.company_name,
        "buyer_contact_name": deal.buyer_contact_name,
        "buyer_contact_email": deal.buyer_contact_email,
        "deal_value_arr": deal.deal_value_arr,
        "stage": deal.stage,
        "close_date": deal.close_date.isoformat() if deal.close_date else None,
        "requested_frameworks": json.loads(deal.requested_frameworks or "[]"),
        "linked_questionnaire_ids": json.loads(deal.linked_questionnaire_ids or "[]"),
        "crm_source": deal.crm_source,
        "crm_external_id": deal.crm_external_id,
        "owner_user_id": deal.owner_user_id,
        "notes": deal.notes,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
    }
