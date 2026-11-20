"""Shareable space service (P1-66, TC-17-005a, TC-17-005b)."""

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.models.answer import Answer
from app.models.document import Document
from app.models.questionnaire import Question, Questionnaire
from app.models.shareable_space import ShareableSpace
from app.models.trust_article import TrustArticle

logger = logging.getLogger(__name__)

ACCESS_AUDIT_ACTION = "shareable_space.accessed"
ROTATE_AUDIT_ACTION = "shareable_space.rotated"
ROTATION_INACTIVE = "This space is inactive and cannot be rotated."
ROTATION_EXPIRED = "This space has expired and cannot be rotated."
ARTICLE_NOT_FOUND = "Article not found"
ANSWER_NOT_FOUND = "Answer not found"
DOCUMENT_NOT_FOUND = "Document not found"
_MAX_TOKEN_LENGTH = 512
_ASSET_DETAILS = {
    "article": ARTICLE_NOT_FOUND,
    "answer": ANSWER_NOT_FOUND,
    "document": DOCUMENT_NOT_FOUND,
}


class ListedAssetNotFound(Exception):
    """An article, answer, or document id is missing or outside this workspace.

    The same detail is used for both cases so a caller cannot tell them apart.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class RotationRefused(Exception):
    """The space is in this workspace, but rotation would bring a dead link back."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _new_raw_token() -> str:
    return secrets.token_urlsafe(32)


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


def _is_expired(space: ShareableSpace, *, now: datetime | None = None) -> bool:
    if not space.expires_at:
        return False
    exp = space.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < (now or datetime.now(timezone.utc))


def _parse_stored_ids(raw: str | None) -> list[int]:
    """Ids from a stored JSON list. Malformed values and non-ids are dropped."""
    try:
        loaded = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    if not isinstance(loaded, list):
        return []
    ids: list[int] = []
    for item in loaded:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            continue
        ids.append(item)
    return ids


def _owned_ids(db: Session, workspace_id: int, ids: set[int], kind: str) -> set[int]:
    """Ids in ``ids`` that are live rows in ``workspace_id``."""
    if not ids:
        return set()
    if kind == "article":
        query = db.query(TrustArticle.id).filter(
            TrustArticle.id.in_(ids),
            TrustArticle.workspace_id == workspace_id,
        )
    elif kind == "answer":
        query = (
            db.query(Answer.id)
            .join(Question, Answer.question_id == Question.id)
            .join(Questionnaire, Question.questionnaire_id == Questionnaire.id)
            .filter(
                Answer.id.in_(ids),
                Questionnaire.workspace_id == workspace_id,
                Questionnaire.deleted_at.is_(None),
            )
        )
    elif kind == "document":
        query = db.query(Document.id).filter(
            Document.id.in_(ids),
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        )
    else:
        raise ValueError(kind)
    return {row[0] for row in query.all()}


def _require_ids(db: Session, workspace_id: int, ids: list[int] | None, kind: str) -> list[int]:
    """Return ``ids`` when every one belongs to the workspace. Otherwise raise.

    A missing id and an id from another workspace use the same detail. Nothing
    is written by this check.
    """
    if not ids:
        return []
    detail = _ASSET_DETAILS[kind]
    cleaned: list[int] = []
    for item in ids:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ListedAssetNotFound(detail)
        cleaned.append(item)
    found = _owned_ids(db, workspace_id, set(cleaned), kind)
    if any(item not in found for item in cleaned):
        raise ListedAssetNotFound(detail)
    return cleaned


def _visible_ids(db: Session, workspace_id: int, raw: str | None, kind: str) -> list[int]:
    """Stored ids that still belong to the workspace, in stored order."""
    ids = _parse_stored_ids(raw)
    if not ids:
        return []
    found = _owned_ids(db, workspace_id, set(ids), kind)
    return [item for item in ids if item in found]


def _space_for_token(db: Session, token: str) -> ShareableSpace | None:
    digest = _digest(token)
    if digest is None:
        return None
    space = db.query(ShareableSpace).filter(ShareableSpace.token_hash == digest).first()
    if space is None or not _same_hash(space.token_hash, digest):
        return None
    return space


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
    # Reject before insert. A foreign or missing id leaves no row.
    articles = _require_ids(db, workspace_id, article_ids, "article")
    answers = _require_ids(db, workspace_id, answer_ids, "answer")
    documents = _require_ids(db, workspace_id, document_ids, "document")
    raw = _new_raw_token()
    space = ShareableSpace(
        workspace_id=workspace_id,
        name=name,
        buyer_company=buyer_company,
        buyer_email=buyer_email,
        opportunity_id=opportunity_id,
        description=description,
        article_ids_json=json.dumps(articles),
        answer_ids_json=json.dumps(answers),
        document_ids_json=json.dumps(documents),
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


def update_space_lists(
    db: Session,
    space_id: int,
    *,
    workspace_id: int,
    lists: dict[str, list[int]],
) -> dict | None:
    """Replace the asset lists named in ``lists``. Other columns stay put.

    Validation finishes before any column is assigned. ``None`` means this
    workspace has no space with that id. A bad id raises and leaves the row
    unchanged.
    """
    space = (
        db.query(ShareableSpace)
        .filter(ShareableSpace.id == space_id, ShareableSpace.workspace_id == workspace_id)
        .first()
    )
    if space is None:
        return None
    validated: dict[str, str] = {}
    if "article_ids" in lists:
        validated["article_ids_json"] = json.dumps(
            _require_ids(db, workspace_id, lists["article_ids"], "article")
        )
    if "answer_ids" in lists:
        validated["answer_ids_json"] = json.dumps(
            _require_ids(db, workspace_id, lists["answer_ids"], "answer")
        )
    if "document_ids" in lists:
        validated["document_ids_json"] = json.dumps(
            _require_ids(db, workspace_id, lists["document_ids"], "document")
        )
    for column, value in validated.items():
        setattr(space, column, value)
    if validated:
        db.flush()
    return _serialize(space, include_admin_indicator=True)


def access_space_by_token(db: Session, token: str) -> dict:
    s = _space_for_token(db, token)
    if s is None:
        return {"valid": False, "reason": "Space not found"}
    if not s.is_active:
        return {"valid": False, "reason": "Space deactivated"}
    if _is_expired(s):
        return {"valid": False, "reason": "Space expired"}
    # Drop ids that are missing, deleted, or no longer in this workspace.
    payload = {
        "valid": True,
        "space": _serialize(s),
        "article_ids": _visible_ids(db, s.workspace_id, s.article_ids_json, "article"),
        "answer_ids": _visible_ids(db, s.workspace_id, s.answer_ids_json, "answer"),
        "document_ids": _visible_ids(db, s.workspace_id, s.document_ids_json, "document"),
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


def rotate_space(db: Session, space_id: int, *, workspace_id: int) -> dict | None:
    """Replace the stored hash. The raw token is returned once, like create.

    The id, contents, expiry, active flag, and any deal ``room_id`` stay as they
    are. Inactive and expired rows are refused before any assignment, so a dead
    link is not brought back. ``None`` means the id is not in this workspace.
    The hash write and the audit row commit in the same transaction.
    """
    space = (
        db.query(ShareableSpace)
        .filter(ShareableSpace.id == space_id, ShareableSpace.workspace_id == workspace_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if space is None:
        return None
    if not space.is_active:
        raise RotationRefused(ROTATION_INACTIVE)
    if _is_expired(space):
        raise RotationRefused(ROTATION_EXPIRED)
    raw = _new_raw_token()
    digest = _digest(raw)
    if digest is None:
        raise RuntimeError("rotation token could not be hashed")
    space.access_token = None
    space.token_hash = digest
    db.flush()
    payload = _serialize(space, raw_token=raw, include_admin_indicator=True)
    # Space id only. Never the new token, its hash, or buyer fields.
    persist_audit(
        db,
        ROTATE_AUDIT_ACTION,
        workspace_id=space.workspace_id,
        resource_type="shareable_space",
        resource_id=space.id,
        details={"space_id": space.id},
    )
    logger.info("shareable_space.rotated space_id=%s", space.id)
    return payload


def live_space_for_token(db: Session, token: str) -> ShareableSpace | None:
    """The space a token may read, or None when the token is not live.

    Unknown, inactive, and expired tokens are the same result. This does not
    write an audit row.
    """
    space = _space_for_token(db, token)
    if space is None or not space.is_active or _is_expired(space):
        return None
    return space


def granted_article(db: Session, space: ShareableSpace, article_id: int) -> TrustArticle | None:
    if article_id not in _parse_stored_ids(space.article_ids_json):
        return None
    return (
        db.query(TrustArticle)
        .filter(TrustArticle.id == article_id, TrustArticle.workspace_id == space.workspace_id)
        .first()
    )


def granted_answer(db: Session, space: ShareableSpace, answer_id: int) -> Answer | None:
    if answer_id not in _parse_stored_ids(space.answer_ids_json):
        return None
    return (
        db.query(Answer)
        .join(Question, Answer.question_id == Question.id)
        .join(Questionnaire, Question.questionnaire_id == Questionnaire.id)
        .filter(
            Answer.id == answer_id,
            Questionnaire.workspace_id == space.workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )


def granted_document(db: Session, space: ShareableSpace, document_id: int) -> Document | None:
    if document_id not in _parse_stored_ids(space.document_ids_json):
        return None
    return (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.workspace_id == space.workspace_id,
            Document.deleted_at.is_(None),
        )
        .first()
    )


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
