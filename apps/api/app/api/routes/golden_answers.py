"""Golden answer library API (P1-71, P1-73, P1-74, P1-75, P1-76)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import golden_answer_service as ga

router = APIRouter(prefix="/golden-answers", tags=["golden-answers"])


class CreateGoldenBody(BaseModel):
    question_text: str
    answer_text: str
    category: str | None = None
    control_ids: list[int] | None = None
    evidence_ids: list[int] | None = None
    confidence: float | None = None
    review_cycle_days: int = 90
    source_answer_id: int | None = None
    customer_override_for: str | None = None


class UpdateGoldenBody(BaseModel):
    question_text: str | None = None
    answer_text: str | None = None
    category: str | None = None
    status: str | None = None
    confidence: float | None = None
    review_cycle_days: int | None = None
    customer_override_for: str | None = None


class SimilarBody(BaseModel):
    question_text: str
    limit: int = 5


@router.post("")
async def create(
    body: CreateGoldenBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ga.create_golden_answer(
        db, session["workspace_id"],
        body.question_text, body.answer_text,
        owner_user_id=session["user_id"],
        category=body.category,
        control_ids=body.control_ids,
        evidence_ids=body.evidence_ids,
        confidence=body.confidence,
        review_cycle_days=body.review_cycle_days,
        source_answer_id=body.source_answer_id,
        customer_override_for=body.customer_override_for,
    )
    db.commit()
    return result


@router.get("")
async def list_all(
    category: str | None = Query(None),
    status: str | None = Query(None),
    customer: str | None = Query(None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"answers": ga.list_golden_answers(db, session["workspace_id"], category, status, customer)}


@router.get("/expiring")
async def expiring(
    within_days: int = Query(14, ge=1),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"expiring": ga.get_expiring(db, session["workspace_id"], within_days)}


@router.get("/{ga_id}")
async def get_one(
    ga_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = ga.get_golden_answer(db, ga_id)
    if not result:
        raise HTTPException(status_code=404)
    return result


@router.get("/{ga_id}/lineage")
async def lineage(
    ga_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = ga.get_lineage(db, ga_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.patch("/{ga_id}")
async def update(
    ga_id: int,
    body: UpdateGoldenBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    result = ga.update_golden_answer(db, ga_id, **updates)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/{ga_id}/review")
async def review(
    ga_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ga.review_golden_answer(db, ga_id)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/{ga_id}/reuse")
async def reuse(
    ga_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = ga.record_reuse(db, ga_id)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/similar")
async def similar(
    body: SimilarBody,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"similar": ga.find_similar(db, session["workspace_id"], body.question_text, body.limit)}
