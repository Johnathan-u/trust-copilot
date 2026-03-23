"""Trust articles CRUD API (TC-01, TC-02)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app.core.auth_deps import require_can_admin, require_valid_session, require_valid_session_optional
from app.core.database import get_db
from app.models import PolicyAcknowledgment, TrustArticle, Workspace

router = APIRouter(prefix="/trust-articles", tags=["trust-articles"])


class TrustArticleCreate(BaseModel):
    slug: str
    title: str
    content: str | None = None
    category: str | None = None
    workspace_id: int | None = None
    published: int = 1
    is_policy: bool = False


class TrustArticleUpdate(BaseModel):
    slug: str | None = None
    title: str | None = None
    content: str | None = None
    category: str | None = None
    published: int | None = None
    is_policy: bool | None = None


def _to_dict(a: TrustArticle) -> dict:
    return {
        "id": a.id,
        "workspace_id": a.workspace_id,
        "slug": a.slug,
        "category": a.category,
        "title": a.title,
        "content": a.content,
        "published": a.published,
        "is_policy": getattr(a, "is_policy", False),
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.get("/")
@router.get("")
def list_trust_articles(
    workspace_id: int | None = Query(None),
    published_only: bool = Query(False, description="When true, only return published articles (for public Trust Center)"),
    policy_only: bool = Query(False, description="When true, only return articles marked as policy (TC-R-B5)"),
    session: dict | None = Depends(require_valid_session_optional),
    db: Session = Depends(get_db),
):
    """List trust articles. Authenticated: current workspace only. Unauthenticated: only when published_only=True and workspace_id set (public Trust Center)."""
    if session and session.get("workspace_id") is not None:
        effective_ws = session.get("workspace_id")
    else:
        if not published_only or workspace_id is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        target_ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not target_ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        effective_ws = workspace_id
    q = db.query(TrustArticle).filter(TrustArticle.workspace_id == effective_ws).order_by(TrustArticle.created_at.desc())
    if published_only:
        q = q.filter(TrustArticle.published == 1)
    if policy_only:
        q = q.filter(TrustArticle.is_policy.is_(True))
    articles = q.all()
    return [_to_dict(a) for a in articles]


@router.get("/policy-acknowledgments")
def list_my_policy_acknowledgments(
    session: dict = Depends(require_valid_session),
    db: Session = Depends(get_db),
):
    """TC-R-B5: Return trust_article_ids the current user has acknowledged (scoped to current workspace)."""
    user_id = session.get("user_id")
    ws = session.get("workspace_id")
    if not user_id:
        return {"acknowledged_article_ids": []}
    rows = (
        db.query(PolicyAcknowledgment.trust_article_id)
        .join(TrustArticle, TrustArticle.id == PolicyAcknowledgment.trust_article_id)
        .filter(PolicyAcknowledgment.user_id == user_id, TrustArticle.workspace_id == ws)
        .all()
    )
    return {"acknowledged_article_ids": [r[0] for r in rows]}


@router.get("/{article_id}")
def get_trust_article(
    article_id: int,
    session: dict | None = Depends(require_valid_session_optional),
    db: Session = Depends(get_db),
):
    """Get a single trust article by id. Authenticated users see own workspace only; unauthenticated see published only."""
    article = db.query(TrustArticle).filter(TrustArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Trust article not found")
    if session and session.get("workspace_id") is not None:
        if article.workspace_id != session.get("workspace_id"):
            raise HTTPException(status_code=404, detail="Trust article not found")
    else:
        if not article.published or article.published != 1:
            raise HTTPException(status_code=404, detail="Trust article not found")
    return _to_dict(article)


@router.post("/")
def create_trust_article(
    body: TrustArticleCreate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create a new trust article. Requires auth."""
    ws = body.workspace_id or session.get("workspace_id")
    if ws is not None and session.get("workspace_id") != ws:
        raise HTTPException(status_code=403, detail="Access denied")
    existing = db.query(TrustArticle).filter(TrustArticle.slug == body.slug).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Slug '{body.slug}' already exists")
    article = TrustArticle(
        workspace_id=body.workspace_id,
        slug=body.slug,
        title=body.title,
        content=body.content or "",
        category=body.category,
        published=body.published,
        is_policy=body.is_policy,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    from app.core.audit import audit_log
    audit_log("trust_article.create", email=session.get("email"), workspace_id=article.workspace_id, resource_type="trust_article", resource_id=article.id, details={"slug": article.slug})
    return _to_dict(article)


@router.patch("/{article_id}")
def update_trust_article(
    article_id: int,
    body: TrustArticleUpdate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update a trust article. Requires auth."""
    article = db.query(TrustArticle).filter(TrustArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Trust article not found")
    if article.workspace_id is not None and session.get("workspace_id") != article.workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if body.slug is not None:
        existing = db.query(TrustArticle).filter(TrustArticle.slug == body.slug, TrustArticle.id != article_id).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Slug '{body.slug}' already exists")
        article.slug = body.slug
    if body.title is not None:
        article.title = body.title
    if body.content is not None:
        article.content = body.content
    if body.category is not None:
        article.category = body.category
    if body.published is not None:
        article.published = body.published
    if body.is_policy is not None:
        article.is_policy = body.is_policy
    db.commit()
    db.refresh(article)
    return _to_dict(article)


@router.delete("/{article_id}")
def delete_trust_article(
    article_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Delete a trust article. Requires auth."""
    article = db.query(TrustArticle).filter(TrustArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Trust article not found")
    if article.workspace_id is not None and session.get("workspace_id") != article.workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    slug, ws_id = article.slug, article.workspace_id
    db.delete(article)
    db.commit()
    from app.core.audit import audit_log
    audit_log("trust_article.delete", email=session.get("email"), workspace_id=ws_id, resource_type="trust_article", resource_id=article_id, details={"slug": slug})
    return {"ok": True}


@router.post("/{article_id}/acknowledge")
def acknowledge_policy(
    article_id: int,
    session: dict = Depends(require_valid_session),
    db: Session = Depends(get_db),
):
    """TC-R-B5: Record that the current user acknowledged this policy (trust article)."""
    article = db.query(TrustArticle).filter(TrustArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Trust article not found")
    if article.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=404, detail="Trust article not found")
    if not article.is_policy:
        raise HTTPException(status_code=400, detail="Article is not marked as a policy")
    user_id = session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    existing = db.query(PolicyAcknowledgment).filter(
        PolicyAcknowledgment.user_id == user_id,
        PolicyAcknowledgment.trust_article_id == article_id,
    ).first()
    if existing:
        return {"ok": True, "acknowledged_at": existing.acknowledged_at.isoformat()}
    now = datetime.now(timezone.utc)
    ack = PolicyAcknowledgment(user_id=user_id, trust_article_id=article_id, acknowledged_at=now)
    db.add(ack)
    db.commit()
    return {"ok": True, "acknowledged_at": now.isoformat()}
