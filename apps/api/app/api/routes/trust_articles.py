"""Trust articles CRUD API (TC-01, TC-02, TC-17-001)."""

import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import (
    require_can_admin,
    require_valid_session,
    require_valid_session_optional,
)
from app.core.database import get_db
from app.core.idempotency import (
    IdempotencyKeyError,
    claim as idempotency_claim,
    get as idempotency_get,
    release as idempotency_release,
    scoped_key,
    set as idempotency_set,
)
from app.models import PolicyAcknowledgment, TrustArticle, TrustArticleVersion, Workspace
from app.services.trust_article_versions import approve_current_draft, revoke_acknowledgments

router = APIRouter(prefix="/trust-articles", tags=["trust-articles"])

_REQUEST_HASH = "_request_hash"
_CREATE_ROUTE = "trust-articles:create"


class TrustArticleCreate(BaseModel):
    slug: str
    title: str
    content: str | None = None
    category: str | None = None
    workspace_id: int | None = None
    published: int = 1
    is_policy: bool = False


class PolicyAcknowledge(BaseModel):
    """The version the reader is acknowledging. Omitted is not a version."""

    article_version_id: int | None = None


class TrustArticleUpdate(BaseModel):
    slug: str | None = None
    title: str | None = None
    content: str | None = None
    category: str | None = None
    published: int | None = None
    is_policy: bool | None = None
    # Accepted only so a different or null value can be rejected. Never written.
    workspace_id: int | None = None


# Same wording for a null, omitted, or different body workspace. This route
# already uses 400 for a body it will not accept (duplicate slug). 422 stays
# the schema-validation status.
_WORKSPACE_DETAIL = "workspace_id must match the current workspace"
_NO_PUBLISHED_POLICY = "Article has no published policy version"
_VERSION_REQUIRED = "article_version_id is required"
_STALE_VERSION = "article_version_id is not the published version"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _load_version(db: Session, article: TrustArticle) -> TrustArticleVersion | None:
    if article.published_version_id is None:
        return None
    return db.get(TrustArticleVersion, article.published_version_id)


def _versions_for(db: Session, articles: list[TrustArticle]) -> dict[int, TrustArticleVersion]:
    ids = [article.published_version_id for article in articles if article.published_version_id]
    if not ids:
        return {}
    rows = db.query(TrustArticleVersion).filter(TrustArticleVersion.id.in_(ids)).all()
    return {row.id: row for row in rows}


def _to_dict(article: TrustArticle, version: TrustArticleVersion | None, *, reader: bool) -> dict:
    """Draft fields for an editor. A reader sees the published snapshot."""
    published_fields = {
        "published_version_id": None,
        "published_version": None,
        "published_slug": None,
        "published_title": None,
        "published_content": None,
        "published_category": None,
        "published_is_policy": None,
    }
    if version is not None:
        published_fields = {
            "published_version_id": version.id,
            "published_version": version.version_number,
            "published_slug": version.slug,
            "published_title": version.title,
            "published_content": version.content,
            "published_category": version.category,
            "published_is_policy": bool(version.is_policy),
        }
    payload = {
        "id": article.id,
        "workspace_id": article.workspace_id,
        "slug": article.slug,
        "category": article.category,
        "title": article.title,
        "content": article.content,
        "published": article.published,
        "is_policy": getattr(article, "is_policy", False),
        "created_at": _iso(article.created_at),
        "updated_at": _iso(article.updated_at),
        **published_fields,
    }
    if reader and article.published == 1 and version is not None:
        payload["slug"] = version.slug
        payload["category"] = version.category
        payload["title"] = version.title
        payload["content"] = version.content
        payload["is_policy"] = bool(version.is_policy)
    return payload


def _session_workspace(session: dict) -> int | None:
    """Positive workspace id from the session, or None when the caller has none."""
    workspace_id = session.get("workspace_id")
    if type(workspace_id) is int and workspace_id > 0:
        return workspace_id
    return None


def _require_body_workspace(session: dict, body_workspace_id: int | None) -> int:
    """Workspace to store. It comes from the session. A null or different body value is 400."""
    workspace_id = _session_workspace(session)
    if workspace_id is None or body_workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail=_WORKSPACE_DETAIL)
    return workspace_id


def _require_article_workspace(article: TrustArticle, session: dict) -> int:
    """403 unless the article belongs to the session workspace. A null workspace does not."""
    workspace_id = _session_workspace(session)
    if workspace_id is None or article.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return workspace_id


def _create_hash(body: TrustArticleCreate) -> str:
    raw = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _idempotency_key(request: Request, workspace_id: int) -> str | None:
    """Optional key scoped to this workspace and the create route. Absent means no claim."""
    names = {name.lower() for name in request.headers.keys()}
    if "idempotency-key" not in names:
        return None
    raw = request.headers.get("Idempotency-Key")
    try:
        key = scoped_key(workspace_id, _CREATE_ROUTE, "new", raw)
    except IdempotencyKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return key or None


def _public_payload(stored: dict) -> dict:
    payload = dict(stored)
    payload.pop(_REQUEST_HASH, None)
    return payload


def _replay(stored: dict, body_hash: str) -> JSONResponse:
    recorded = stored.get(_REQUEST_HASH)
    if isinstance(recorded, str) and recorded != body_hash:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key was already used with a different request body",
        )
    return JSONResponse(content=_public_payload(stored), status_code=200)


def _claim_or_replay(
    db: Session, key: str | None, body_hash: str
) -> tuple[JSONResponse | None, str | None]:
    if not key:
        return None, None
    cached = idempotency_get(db, key)
    if cached:
        return _replay(cached[1], body_hash), None
    owner = idempotency_claim(db, key)
    if owner is None:
        cached_again = idempotency_get(db, key)
        if cached_again:
            return _replay(cached_again[1], body_hash), None
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    return None, owner


def _release_claim(db: Session, key: str | None, owner: str | None) -> None:
    if key and owner:
        idempotency_release(db, key, owner=owner)


@router.get("/")
@router.get("")
def list_trust_articles(
    workspace_id: int | None = Query(None),
    published_only: bool = Query(
        False, description="When true, only return published articles (for public Trust Center)"
    ),
    policy_only: bool = Query(
        False, description="When true, only return articles marked as policy (TC-R-B5)"
    ),
    session: dict | None = Depends(require_valid_session_optional),
    db: Session = Depends(get_db),
):
    """List trust articles.

    Authenticated callers see the current workspace. Anonymous callers must
    pass published_only and a workspace id. published_only returns the
    approved version, which is what the public trust centre shows.
    """
    if session and session.get("workspace_id") is not None:
        effective_ws = session.get("workspace_id")
    else:
        if not published_only or workspace_id is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        target_ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not target_ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        effective_ws = workspace_id
    q = (
        db.query(TrustArticle)
        .filter(
            TrustArticle.workspace_id == effective_ws,
            TrustArticle.workspace_id.isnot(None),
        )
        .order_by(TrustArticle.created_at.desc())
    )
    if published_only:
        q = q.filter(TrustArticle.published == 1)
    if policy_only:
        q = q.filter(TrustArticle.is_policy.is_(True))
    articles = q.all()
    versions = _versions_for(db, articles)
    # published_only is the public trust centre. It returns the approved version.
    return [
        _to_dict(article, versions.get(article.published_version_id), reader=published_only)
        for article in articles
    ]


@router.get("/policy-acknowledgments")
def list_my_policy_acknowledgments(
    session: dict = Depends(require_valid_session),
    db: Session = Depends(get_db),
):
    """Return articles whose current published version this user has acknowledged."""
    user_id = session.get("user_id")
    ws = session.get("workspace_id")
    if not user_id:
        return {"acknowledged_article_ids": []}
    rows = (
        db.query(PolicyAcknowledgment.trust_article_id)
        .join(TrustArticle, TrustArticle.id == PolicyAcknowledgment.trust_article_id)
        .filter(
            PolicyAcknowledgment.user_id == user_id,
            PolicyAcknowledgment.workspace_id == ws,
            PolicyAcknowledgment.revoked_at.is_(None),
            PolicyAcknowledgment.article_version_id == TrustArticle.published_version_id,
            TrustArticle.workspace_id == ws,
            TrustArticle.published == 1,
        )
        .all()
    )
    return {"acknowledged_article_ids": [row[0] for row in rows]}


@router.get("/{article_id}")
def get_trust_article(
    article_id: int,
    workspace_id: int | None = Query(None),
    session: dict | None = Depends(require_valid_session_optional),
    db: Session = Depends(get_db),
):
    """Get one trust article.

    A signed-in caller sees only their workspace. With no workspace_id, that
    caller sees the draft. A public read (no session, or a named workspace,
    which is what the trust centre sends) sees the published version.
    An anonymous caller never sees an article whose workspace is null.
    """
    article = db.query(TrustArticle).filter(TrustArticle.id == article_id).first()
    if not article or article.workspace_id is None:
        raise HTTPException(status_code=404, detail="Trust article not found")
    if session and session.get("workspace_id") is not None:
        if article.workspace_id != session.get("workspace_id"):
            raise HTTPException(status_code=404, detail="Trust article not found")
        reader = workspace_id is not None
    else:
        if not article.published or article.published != 1:
            raise HTTPException(status_code=404, detail="Trust article not found")
        if workspace_id is not None and article.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Trust article not found")
        reader = True
    return _to_dict(article, _load_version(db, article), reader=reader)


@router.post("/")
def create_trust_article(
    body: TrustArticleCreate,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create a trust article. The workspace is the session's.

    ``published`` 1 (the default) stores version 1. A later retry with the same
    Idempotency-Key returns that article and does not insert another.
    """
    ws = _require_body_workspace(session, body.workspace_id)
    body_hash = _create_hash(body)
    key = _idempotency_key(request, ws)
    replay, owner = _claim_or_replay(db, key, body_hash)
    if replay is not None:
        return replay
    try:
        existing = (
            db.query(TrustArticle)
            .filter(TrustArticle.slug == body.slug, TrustArticle.workspace_id == ws)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail=f"Slug '{body.slug}' already exists")
        article = TrustArticle(
            workspace_id=ws,
            slug=body.slug,
            title=body.title,
            content=body.content or "",
            category=body.category,
            published=body.published,
            is_policy=body.is_policy,
        )
        db.add(article)
        db.flush()
        version = None
        if article.published == 1:
            version = approve_current_draft(db, article)
        payload = _to_dict(article, version, reader=False)
        if key and owner:
            idempotency_set(
                db,
                key,
                200,
                {**payload, _REQUEST_HASH: body_hash},
                owner=owner,
                commit=False,
            )
        db.commit()
        db.refresh(article)
    except Exception:
        db.rollback()
        _release_claim(db, key, owner)
        raise
    from app.core.audit import audit_log

    audit_log(
        "trust_article.create",
        email=session.get("email"),
        workspace_id=article.workspace_id,
        resource_type="trust_article",
        resource_id=article.id,
        details={"slug": article.slug},
    )
    return payload


@router.patch("/{article_id}")
def update_trust_article(
    article_id: int,
    body: TrustArticleUpdate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update the draft. ``published: 1`` approves it. Any other value withdraws it."""
    article = db.query(TrustArticle).filter(TrustArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Trust article not found")
    _require_article_workspace(article, session)
    if "workspace_id" in body.model_fields_set and body.workspace_id != article.workspace_id:
        raise HTTPException(status_code=400, detail=_WORKSPACE_DETAIL)
    if body.slug is not None:
        existing = (
            db.query(TrustArticle)
            .filter(
                TrustArticle.slug == body.slug,
                TrustArticle.workspace_id == article.workspace_id,
                TrustArticle.id != article_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail=f"Slug '{body.slug}' already exists")
        article.slug = body.slug
    if body.title is not None:
        article.title = body.title
    if body.content is not None:
        article.content = body.content
    if body.category is not None:
        article.category = body.category
    if body.is_policy is not None:
        article.is_policy = body.is_policy
    version = _load_version(db, article)
    if body.published is not None:
        if body.published == 1:
            version = approve_current_draft(db, article)
        else:
            article.published = body.published
            revoke_acknowledgments(db, article.id)
    db.commit()
    db.refresh(article)
    return _to_dict(article, version, reader=False)


@router.delete("/{article_id}")
def delete_trust_article(
    article_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Delete a trust article. Requires auth. A null workspace is not the caller's."""
    article = db.query(TrustArticle).filter(TrustArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Trust article not found")
    _require_article_workspace(article, session)
    slug, ws_id = article.slug, article.workspace_id
    db.delete(article)
    db.commit()
    from app.core.audit import audit_log

    audit_log(
        "trust_article.delete",
        email=session.get("email"),
        workspace_id=ws_id,
        resource_type="trust_article",
        resource_id=article_id,
        details={"slug": slug},
    )
    return {"ok": True}


def _viewable_version(db: Session, article: TrustArticle) -> TrustArticleVersion | None:
    """The published snapshot a reader may acknowledge.

    Acknowledging never publishes. A missing published version is a 400 from
    the caller. Only an administrator publish calls approve_current_draft.
    """
    if article.published != 1:
        return None
    return _load_version(db, article)


@router.post("/{article_id}/acknowledge")
def acknowledge_policy(
    article_id: int,
    body: PolicyAcknowledge | None = None,
    session: dict = Depends(require_valid_session),
    db: Session = Depends(get_db),
):
    """Record that this user acknowledged the published version they were shown.

    ``article_version_id`` must be that published version. A different id is 409.
    A missing id is 422. Another workspace is 404, same as a missing article.
    """
    article = db.query(TrustArticle).filter(TrustArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Trust article not found")
    if article.workspace_id is None or article.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=404, detail="Trust article not found")
    user_id = session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    workspace_id = _session_workspace(session)
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="Trust article not found")
    if body is None or body.article_version_id is None:
        raise HTTPException(status_code=422, detail=_VERSION_REQUIRED)
    version = _viewable_version(db, article)
    if version is None:
        raise HTTPException(status_code=400, detail=_NO_PUBLISHED_POLICY)
    if body.article_version_id != version.id:
        raise HTTPException(status_code=409, detail=_STALE_VERSION)
    if not version.is_policy:
        raise HTTPException(status_code=400, detail="Article is not marked as a policy")
    existing = (
        db.query(PolicyAcknowledgment)
        .filter(
            PolicyAcknowledgment.user_id == user_id,
            PolicyAcknowledgment.article_version_id == version.id,
        )
        .first()
    )
    if existing and existing.revoked_at is None:
        return _ack_payload(existing, version.id, workspace_id)
    now = datetime.now(timezone.utc)
    if existing:
        existing.revoked_at = None
        existing.acknowledged_at = now
        existing.workspace_id = workspace_id
        ack = existing
    else:
        ack = PolicyAcknowledgment(
            user_id=user_id,
            trust_article_id=article_id,
            article_version_id=version.id,
            workspace_id=workspace_id,
            acknowledged_at=now,
        )
        db.add(ack)
    db.commit()
    db.refresh(ack)
    return _ack_payload(ack, version.id, workspace_id)


def _ack_payload(ack: PolicyAcknowledgment, version_id: int, workspace_id: int) -> dict:
    return {
        "ok": True,
        "acknowledged_at": _iso(ack.acknowledged_at),
        "article_version_id": version_id,
        "workspace_id": workspace_id,
    }
