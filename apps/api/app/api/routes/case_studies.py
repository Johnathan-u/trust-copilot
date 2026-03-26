"""Case study API (P0-83)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import case_study_service as cs

router = APIRouter(prefix="/case-studies", tags=["case-studies"])


class CreateCaseStudyRequest(BaseModel):
    title: str
    company_name: str | None = None
    industry: str | None = None
    company_size: str | None = None
    challenge: str | None = None
    solution: str | None = None
    results: str | None = None
    quote: str | None = None
    quote_attribution: str | None = None
    metrics: dict | None = None


class UpdateCaseStudyRequest(BaseModel):
    title: str | None = None
    company_name: str | None = None
    industry: str | None = None
    company_size: str | None = None
    challenge: str | None = None
    solution: str | None = None
    results: str | None = None
    quote: str | None = None
    quote_attribution: str | None = None
    metrics: dict | None = None
    status: str | None = None


@router.get("/template")
async def get_template():
    return cs.get_template()


@router.get("")
async def list_case_studies(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"case_studies": cs.list_all(db, session["workspace_id"])}


@router.post("")
async def create_case_study(
    req: CreateCaseStudyRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = cs.create(db, session["workspace_id"], req.title, **req.model_dump(exclude={"title"}))
    db.commit()
    return result


@router.get("/{case_id}")
async def get_case_study(
    case_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = cs.get(db, case_id)
    if not result:
        raise HTTPException(status_code=404, detail="Case study not found")
    return result


@router.patch("/{case_id}")
async def update_case_study(
    case_id: int,
    req: UpdateCaseStudyRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = cs.update(db, case_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Case study not found")
    db.commit()
    return result


@router.delete("/{case_id}")
async def delete_case_study(
    case_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    if not cs.delete(db, case_id):
        raise HTTPException(status_code=404, detail="Case study not found")
    db.commit()
    return {"deleted": True}
