"""Shareable space service (P1-66)."""

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.shareable_space import ShareableSpace

logger = logging.getLogger(__name__)


def create_space(
    db: Session,
    workspace_id: int,
    name: str,
    created_by: int,
    buyer_company: str | None = None,
    buyer_email: str | None = None,
    opportunity_id: str | None = None,
    description: str | None = None,
    article_ids: list[int] | None = None,
    answer_ids: list[int] | None = None,
    document_ids: list[int] | None = None,
    expires_days: int = 30,
) -> dict:
    space = ShareableSpace(
        workspace_id=workspace_id,
        name=name,
        buyer_company=buyer_company,
        buyer_email=buyer_email,
        opportunity_id=opportunity_id,
        description=description,
        article_ids_json=json.dumps(article_ids or []),
        answer_ids_json=json.dumps(answer_ids or []),
        document_ids_json=json.dumps(document_ids or []),
        access_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
        created_by_user_id=created_by,
    )
    db.add(space)
    db.flush()
    return _serialize(space)


def list_spaces(db: Session, workspace_id: int) -> list[dict]:
    spaces = db.query(ShareableSpace).filter(
        ShareableSpace.workspace_id == workspace_id,
    ).order_by(ShareableSpace.created_at.desc()).all()
    return [_serialize(s) for s in spaces]


def get_space(db: Session, space_id: int) -> dict | None:
    s = db.query(ShareableSpace).filter(ShareableSpace.id == space_id).first()
    return _serialize(s) if s else None


def deactivate_space(db: Session, space_id: int) -> dict | None:
    s = db.query(ShareableSpace).filter(ShareableSpace.id == space_id).first()
    if not s:
        return None
    s.is_active = False
    db.flush()
    return _serialize(s)


def access_space_by_token(db: Session, token: str) -> dict:
    s = db.query(ShareableSpace).filter(ShareableSpace.access_token == token).first()
    if not s:
        return {"valid": False, "reason": "Space not found"}
    if not s.is_active:
        return {"valid": False, "reason": "Space deactivated"}
    if s.expires_at:
        exp = s.expires_at.replace(tzinfo=timezone.utc) if s.expires_at.tzinfo is None else s.expires_at
        if exp < datetime.now(timezone.utc):
            return {"valid": False, "reason": "Space expired"}
    return {
        "valid": True,
        "space": _serialize(s),
        "article_ids": json.loads(s.article_ids_json or "[]"),
        "answer_ids": json.loads(s.answer_ids_json or "[]"),
        "document_ids": json.loads(s.document_ids_json or "[]"),
    }


def _serialize(s: ShareableSpace) -> dict:
    return {
        "id": s.id,
        "workspace_id": s.workspace_id,
        "name": s.name,
        "buyer_company": s.buyer_company,
        "buyer_email": s.buyer_email,
        "opportunity_id": s.opportunity_id,
        "access_token": s.access_token,
        "is_active": s.is_active,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
