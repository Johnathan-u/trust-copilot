"""Security and data-handling FAQ API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import security_faq_service as faq_svc

router = APIRouter(prefix="/security-faq", tags=["security-faq"])


class CreateFAQRequest(BaseModel):
    category: str
    question: str
    answer: str
    framework_tags: str | None = None


class UpdateFAQRequest(BaseModel):
    category: str | None = None
    question: str | None = None
    answer: str | None = None
    framework_tags: str | None = None


@router.get("")
async def list_faqs(
    category: str | None = Query(None),
    search: str | None = Query(None),
    framework: str | None = Query(None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """List security FAQ entries (all authenticated users)."""
    workspace_id = session["workspace_id"]
    items = faq_svc.list_faqs(db, workspace_id, category=category, search=search, framework=framework)
    return {"faqs": items}


@router.get("/categories")
async def list_categories(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """List distinct FAQ categories."""
    workspace_id = session["workspace_id"]
    return {"categories": faq_svc.get_categories(db, workspace_id)}


@router.get("/{faq_id}")
async def get_faq(
    faq_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Get a single FAQ entry."""
    item = faq_svc.get_faq(db, faq_id)
    if not item:
        raise HTTPException(status_code=404, detail="FAQ not found")
    if item["workspace_id"] != session["workspace_id"]:
        raise HTTPException(status_code=403, detail="Not your workspace")
    return item


@router.post("/seed")
async def seed_defaults(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Seed default security FAQ entries for the workspace."""
    workspace_id = session["workspace_id"]
    created = faq_svc.seed_defaults(db, workspace_id)
    db.commit()
    return {"created": created}


@router.post("")
async def create_faq(
    req: CreateFAQRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create a custom FAQ entry (admin only)."""
    workspace_id = session["workspace_id"]
    if not req.question.strip() or not req.answer.strip():
        raise HTTPException(status_code=400, detail="Question and answer are required")
    item = faq_svc.create_faq(
        db, workspace_id, req.category.strip(), req.question.strip(),
        req.answer.strip(), framework_tags=req.framework_tags,
    )
    db.commit()
    return item


@router.patch("/{faq_id}")
async def update_faq(
    faq_id: int,
    req: UpdateFAQRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update a FAQ entry (admin only)."""
    existing = faq_svc.get_faq(db, faq_id)
    if not existing:
        raise HTTPException(status_code=404, detail="FAQ not found")
    if existing["workspace_id"] != session["workspace_id"]:
        raise HTTPException(status_code=403, detail="Not your workspace")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = faq_svc.update_faq(db, faq_id, **updates)
    db.commit()
    return result


@router.delete("/{faq_id}")
async def delete_faq(
    faq_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Delete a FAQ entry (admin only)."""
    existing = faq_svc.get_faq(db, faq_id)
    if not existing:
        raise HTTPException(status_code=404, detail="FAQ not found")
    if existing["workspace_id"] != session["workspace_id"]:
        raise HTTPException(status_code=403, detail="Not your workspace")
    faq_svc.delete_faq(db, faq_id)
    db.commit()
    return {"deleted": True}
