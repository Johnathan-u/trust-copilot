"""Control engine API (P1-31, P1-34, P1-35, P1-36)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import control_engine_service as ce

router = APIRouter(prefix="/control-engine", tags=["control-engine"])


@router.post("/evaluate/{control_id}")
async def evaluate_control(
    control_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ce.evaluate_control(db, session["workspace_id"], control_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    db.commit()
    return result


@router.post("/evaluate-all")
async def evaluate_all(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ce.evaluate_all_controls(db, session["workspace_id"])
    db.commit()
    return result


@router.get("/timeline/{control_id}")
async def control_timeline(
    control_id: int,
    limit: int = Query(20, ge=1, le=100),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"timeline": ce.get_control_timeline(db, session["workspace_id"], control_id, limit)}


@router.get("/drift")
async def drift_report(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"drifts": ce.get_drift_report(db, session["workspace_id"])}
