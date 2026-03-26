"""Confidence-based routing API (P1-57)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import confidence_routing_service as svc

router = APIRouter(prefix="/confidence-routing", tags=["confidence-routing"])


class RouteBatchBody(BaseModel):
    question_ids: list[int]


class ThresholdBody(BaseModel):
    high: int = 70
    low: int = 40


@router.get("/question/{question_id}")
async def route_question(question_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.route_question(db, question_id)


@router.get("/queue/{questionnaire_id}")
async def review_queue(questionnaire_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"queue": svc.get_review_queue(db, questionnaire_id)}


@router.post("/batch")
async def batch(body: RouteBatchBody, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.route_batch(db, body.question_ids)


@router.get("/thresholds")
async def get_thresholds(session: dict = Depends(require_session)):
    return svc.get_thresholds()


@router.post("/thresholds")
async def set_thresholds(body: ThresholdBody, session: dict = Depends(require_can_admin)):
    return svc.set_thresholds(body.high, body.low)
