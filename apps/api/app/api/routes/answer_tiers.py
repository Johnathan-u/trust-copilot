"""Answer tiers API (P1-69)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import answer_tiers_service as at

router = APIRouter(prefix="/answer-tiers", tags=["answer-tiers"])


class SetTierBody(BaseModel):
    answer_id: int
    tier: str


@router.post("")
async def set_tier(
    body: SetTierBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = at.set_answer_tier(db, body.answer_id, body.tier)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Answer not found")
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.get("/classify")
async def classify(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return at.classify_answers(db)
