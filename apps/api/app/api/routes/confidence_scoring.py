"""Source confidence scoring API (P1-46)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import confidence_scoring_service as svc

router = APIRouter(prefix="/confidence-scoring", tags=["confidence-scoring"])


@router.get("/evidence/{evidence_id}")
async def score_evidence(evidence_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.score_evidence(db, evidence_id)


@router.get("/control/{control_id}")
async def score_control(control_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"scores": svc.score_all_for_control(db, control_id)}
