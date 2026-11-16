"""Shareable space service (P1-66, TC-17-005a)."""

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.models.shareable_space import ShareableSpace

logger = logging.getLogger(__name__)

ACCESS_AUDIT_ACTION = "shareable_space.accessed"
_MAX_TOKEN_LENGTH = 512


def _digest(token: str) -> str | None:
    """SHA-256 hex of the UTF-8 token. The migration uses this same encoding."""
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _same_hash(stored: str | None, digest: str) -> bool:
    """Constant-time compare of two SHA-256 hex digests."""
    if not stored or len(stored) != len(digest):
        return False
    return hmac.compare_digest(stored, digest)


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
    raw = secrets.token_urlsafe(32)
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
        access_token=None,
        token_hash=_digest(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
        created_by_user_id=created_by,
    )
    db.add(space)
    db.flush()
    # The raw token exists only in this response. Later reads cannot rebuild it.
    return _serialize(space, raw_token=raw, include_admin_indicator=True)


def list_spaces(
    db: Session, workspace_id: int, *, include_admin_indicator: bool = False
) -> list[dict]:
    spaces = (
        db.query(ShareableSpace)
        .filter(
            ShareableSpace.workspace_id == workspace_id,
        )
        .order_by(ShareableSpace.created_at.desc())
        .all()
    )
    return [_serialize(s, include_admin_indicator=include_admin_indicator) for s in spaces]


def get_space(db: Session, space_id: int, *, include_admin_indicator: bool = False) -> dict | None:
    s = db.query(ShareableSpace).filter(ShareableSpace.id == space_id).first()
    if not s:
        return None
    return _serialize(s, include_admin_indicator=include_admin_indicator)


def deactivate_space(db: Session, space_id: int, *, workspace_id: int) -> dict | None:
    s = (
        db.query(ShareableSpace)
        .filter(ShareableSpace.id == space_id, ShareableSpace.workspace_id == workspace_id)
        .first()
    )
    if not s:
        return None
    s.is_active = False
    db.flush()
    return _serialize(s, include_admin_indicator=True)


def access_space_by_token(db: Session, token: str) -> dict:
    digest = _digest(token)
    if digest is None:
        return {"valid": False, "reason": "Space not found"}
    s = db.query(ShareableSpace).filter(ShareableSpace.token_hash == digest).first()
    if s is None or not _same_hash(s.token_hash, digest):
        return {"valid": False, "reason": "Space not found"}
    if not s.is_active:
        return {"valid": False, "reason": "Space deactivated"}
    if s.expires_at:
        exp = (
            s.expires_at.replace(tzinfo=timezone.utc)
            if s.expires_at.tzinfo is None
            else s.expires_at
        )
        if exp < datetime.now(timezone.utc):
            return {"valid": False, "reason": "Space expired"}
    payload = {
        "valid": True,
        "space": _serialize(s),
        "article_ids": json.loads(s.article_ids_json or "[]"),
        "answer_ids": json.loads(s.answer_ids_json or "[]"),
        "document_ids": json.loads(s.document_ids_json or "[]"),
    }
    # Space id only. Never the presented token or the stored hash.
    logger.info("shareable_space.accessed space_id=%s", s.id)
    persist_audit(
        db,
        ACCESS_AUDIT_ACTION,
        workspace_id=s.workspace_id,
        resource_type="shareable_space",
        resource_id=s.id,
        details={"space_id": s.id},
    )
    return payload


def _serialize(
    s: ShareableSpace,
    *,
    raw_token: str | None = None,
    include_admin_indicator: bool = False,
) -> dict:
    body = {
        "id": s.id,
        "workspace_id": s.workspace_id,
        "name": s.name,
        "buyer_company": s.buyer_company,
        "buyer_email": s.buyer_email,
        "opportunity_id": s.opportunity_id,
        "access_token": raw_token,
        "is_active": s.is_active,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
    if include_admin_indicator:
        body["has_access_token"] = bool(s.token_hash)
    return body
