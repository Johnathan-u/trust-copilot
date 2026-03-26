"""Alert management API (P1-38, P1-39)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import alert_management_service as am

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AcknowledgeRequest(BaseModel):
    alert_type: str
    action: str
    control_id: int | None = None
    reason: str | None = None
    snooze_hours: int | None = None


@router.post("/acknowledge")
async def acknowledge_alert(
    req: AcknowledgeRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = am.acknowledge(
        db, session["workspace_id"], req.alert_type, req.action,
        control_id=req.control_id, reason=req.reason,
        snooze_hours=req.snooze_hours, user_id=session.get("user_id"),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.get("")
async def list_acknowledgments(
    control_id: int | None = Query(None),
    active_only: bool = Query(False),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"acknowledgments": am.list_acknowledgments(db, session["workspace_id"], control_id, active_only)}
