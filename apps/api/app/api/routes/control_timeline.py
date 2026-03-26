"""Control timeline view API (P1-40)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import control_timeline_service as ct

router = APIRouter(prefix="/control-timeline", tags=["control-timeline"])


@router.get("/{control_id}")
async def get_timeline(
    control_id: int,
    limit: int = Query(50, ge=1, le=200),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = ct.get_control_timeline(db, session["workspace_id"], control_id, limit)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
