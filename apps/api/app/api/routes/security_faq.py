"""Security and data-handling FAQ API."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_deps import _resolve_permission, require_session
from app.models import WorkspaceMember
from app.core import idempotency
import hashlib
import json
from app.core.database import get_db
from app.services import security_faq_service as faq_svc

router = APIRouter(prefix="/security-faq", tags=["security-faq"])


def _check_current_permission(db, session, permission=None):
    user_id = session.get("user_id")
    if user_id is not None:
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.workspace_id == session.get("workspace_id"),
            )
            .with_for_update(read=True)
            .populate_existing()
            .first()
        )
        if member is None or member.suspended:
            raise HTTPException(403, "Workspace access is unavailable")
        session = {**session, "role": member.role}
    if permission and not _resolve_permission(
        session.get("role"), permission, session.get("workspace_id"), db
    ):
        raise HTTPException(403, "Insufficient permissions")
    return session


def _current_permission(permission=None):
    async def dependency(request: Request, db: Session = Depends(get_db)):
        session = await require_session(request, db)
        return _check_current_permission(db, session, permission)

    return dependency


require_faq_session = _current_permission()
require_faq_admin = _current_permission("can_admin")
require_faq_review = _current_permission("can_review")


class FAQContent(BaseModel):
    @field_validator("source_evidence_ids", check_fields=False, mode="before")
    @classmethod
    def source_ids(cls, value):
        if value is not None and (
            not isinstance(value, list)
            or any(
                isinstance(i, bool) or not isinstance(i, int) or not 0 < i <= 2147483647
                for i in value
            )
        ):
            raise ValueError("Use valid evidence identifiers")
        return value

    @field_validator(
        "category", "question", "answer", "framework_tags", check_fields=False, mode="before"
    )
    @classmethod
    def safe_text(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("Text is required")
        if any((ord(c) < 32 and c not in "\n\r\t") or 127 <= ord(c) <= 159 for c in value):
            raise ValueError("Unsupported control character")
        value = value.strip()
        if not value:
            raise ValueError("Text must not be blank")
        return value


class CreateFAQRequest(FAQContent):
    category: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=20000)
    framework_tags: str | None = Field(default=None, max_length=512)
    source_evidence_ids: list[int] = Field(default_factory=list, max_length=20)


class UpdateFAQRequest(FAQContent):
    category: str | None = Field(default=None, min_length=1, max_length=64)
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    answer: str | None = Field(default=None, min_length=1, max_length=20000)
    framework_tags: str | None = Field(default=None, max_length=512)
    source_evidence_ids: list[int] | None = Field(default=None, max_length=20)
    expected_revision: int | None = Field(default=None, ge=1)


class ReviewAction(BaseModel):
    expected_revision: int = Field(ge=1)
    verified: bool = False


def _commit(db, operation):
    try:
        result = operation()
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "The FAQ change could not be saved. Reload and try again."
        ) from None
    except Exception:
        db.rollback()
        raise


@router.get("")
async def list_faqs(
    category: str | None = Query(None, max_length=64),
    search: str | None = Query(None, max_length=2000),
    framework: str | None = Query(None, max_length=512),
    session: dict = Depends(require_faq_session),
    db: Session = Depends(get_db),
):
    """List workspace FAQ drafts and reviewed entries."""
    return {"faqs": faq_svc.list_faqs(db, session["workspace_id"], category, search, framework)}


@router.get("/categories")
async def list_categories(
    session: dict = Depends(require_faq_session), db: Session = Depends(get_db)
):
    """List workspace FAQ categories."""
    return {"categories": faq_svc.get_categories(db, session["workspace_id"])}


@router.get("/published")
async def published_faqs(
    session: dict = Depends(require_faq_session), db: Session = Depends(get_db)
):
    """Read reviewed FAQ entries whose published revision still has approved support."""
    return {"faqs": faq_svc.list_published_faqs(db, session["workspace_id"])}


@router.get("/{faq_id}/revisions")
async def revision_history(
    faq_id: int, session: dict = Depends(require_faq_session), db: Session = Depends(get_db)
):
    """Read saved content revisions for a workspace FAQ entry."""
    return {"revisions": faq_svc.revisions(db, session["workspace_id"], faq_id)}


@router.get("/{faq_id}")
async def get_faq(
    faq_id: int, session: dict = Depends(require_faq_session), db: Session = Depends(get_db)
):
    """Read a workspace FAQ entry."""
    item = faq_svc.get_faq(db, faq_id, session["workspace_id"])
    if item is None:
        raise HTTPException(404, "FAQ not found")
    return item


@router.post("/seed")
async def seed_defaults(session: dict = Depends(require_faq_admin), db: Session = Depends(get_db)):
    """Create synthetic FAQ templates for later editing and review."""
    return _commit(db, lambda: {"created": faq_svc.seed_defaults(db, session["workspace_id"])})


@router.post("")
async def create_faq(
    req: CreateFAQRequest,
    session: dict = Depends(require_faq_admin),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Create a draft FAQ entry with optional same-workspace source evidence."""
    key = idempotency.scoped_key(session["workspace_id"], "faq", "create", idempotency_key)
    fingerprint = hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True).encode()).hexdigest()
    owner = None
    if key:
        cached = idempotency.get(db, key)
        if cached:
            if cached[1].get("fingerprint") != fingerprint:
                raise HTTPException(409, "This request key was already used with different content")
            return cached[1]["response"]
        owner = idempotency.claim(db, key)
        if owner is None:
            raise HTTPException(409, "This request is already in progress")
    try:

        def operation():
            # Claiming a retry key commits its short lease. Reacquire authorization after it.
            if key:
                _check_current_permission(db, session, "can_admin")
            result = faq_svc.create_faq(
                db, session["workspace_id"], **req.model_dump(), actor_id=session.get("user_id")
            )
            if key:
                idempotency.set(
                    db,
                    key,
                    200,
                    {"fingerprint": fingerprint, "response": result},
                    owner=owner,
                    commit=False,
                )
            return result

        return _commit(db, operation)
    except Exception:
        db.rollback()
        if key:
            idempotency.release(db, key, owner=owner)
        raise


@router.patch("/{faq_id}")
async def update_faq(
    faq_id: int,
    req: UpdateFAQRequest,
    session: dict = Depends(require_faq_admin),
    db: Session = Depends(get_db),
):
    """Edit FAQ content and invalidate review and publication of earlier content."""

    def operation():
        item = faq_svc.update_faq(
            db,
            faq_id,
            workspace_id=session["workspace_id"],
            actor_id=session.get("user_id"),
            **req.model_dump(exclude_unset=True),
        )
        if item is None:
            raise HTTPException(404, "FAQ not found")
        return item

    return _commit(db, operation)


@router.delete("/{faq_id}")
async def delete_faq(
    faq_id: int, session: dict = Depends(require_faq_admin), db: Session = Depends(get_db)
):
    """Delete a workspace FAQ entry and its content versions."""

    def operation():
        if not faq_svc.delete_faq(db, faq_id, session["workspace_id"], session.get("user_id")):
            raise HTTPException(404, "FAQ not found")
        return {"deleted": True}

    return _commit(db, operation)


@router.post("/{faq_id}/approve")
async def approve_faq(
    faq_id: int,
    body: ReviewAction,
    session: dict = Depends(require_faq_review),
    db: Session = Depends(get_db),
):
    """Record human verification of the current content and its source evidence."""
    return _commit(
        db,
        lambda: faq_svc.transition(
            db,
            session["workspace_id"],
            faq_id,
            "approve",
            body.expected_revision,
            session.get("user_id"),
            verified=body.verified,
        ),
    )


@router.post("/{faq_id}/publish")
async def publish_faq(
    faq_id: int,
    body: ReviewAction,
    session: dict = Depends(require_faq_admin),
    db: Session = Depends(get_db),
):
    """Publish the current approved revision."""
    return _commit(
        db,
        lambda: faq_svc.transition(
            db,
            session["workspace_id"],
            faq_id,
            "publish",
            body.expected_revision,
            session.get("user_id"),
        ),
    )


@router.post("/{faq_id}/withdraw")
async def withdraw_faq(
    faq_id: int,
    body: ReviewAction,
    session: dict = Depends(require_faq_admin),
    db: Session = Depends(get_db),
):
    """Withdraw a published FAQ entry."""
    return _commit(
        db,
        lambda: faq_svc.transition(
            db,
            session["workspace_id"],
            faq_id,
            "withdraw",
            body.expected_revision,
            session.get("user_id"),
        ),
    )
