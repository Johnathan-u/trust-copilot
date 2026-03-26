"""Signal mapping API (P1-32)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import signal_mapping_service as sm

router = APIRouter(prefix="/signal-mappings", tags=["signal-mappings"])


class EvaluateSignalRequest(BaseModel):
    signal: str
    value: bool
    metadata: dict | None = None


@router.get("")
async def get_signal_map(session: dict = Depends(require_session)):
    return {"mappings": sm.get_signal_map()}


@router.get("/coverage")
async def coverage_matrix(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return sm.get_coverage_matrix(db, session["workspace_id"])


@router.post("/evaluate")
async def evaluate_signal(
    req: EvaluateSignalRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return sm.evaluate_signal(db, session["workspace_id"], req.signal, req.value, req.metadata)
