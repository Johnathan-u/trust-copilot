"""Trust promises API (E2-08, E2-10, E2-11, E2-12, E2-13)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import promise_service as svc

router = APIRouter(prefix="/promises", tags=["promises"])


class CreatePromiseBody(BaseModel):
    promise_text: str
    source_type: str
    source_ref_id: int | None = None
    owner_user_id: int | None = None
    deal_id: int | None = None
    control_ids: list[int] | None = None
    evidence_ids: list[int] | None = None
    topic_key: str | None = None


class MapControlsBody(BaseModel):
    control_ids: list[int]


@router.post("")
async def create(body: CreatePromiseBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.create_promise(
        db, session["workspace_id"], body.promise_text, body.source_type,
        source_ref_id=body.source_ref_id, owner_user_id=body.owner_user_id or session.get("user_id"),
        deal_id=body.deal_id, control_ids=body.control_ids, evidence_ids=body.evidence_ids,
        topic_key=body.topic_key,
    )
    db.commit()
    return result


@router.get("")
async def list_all(
    status: str | None = Query(None),
    deal_id: int | None = Query(None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"promises": svc.list_promises(db, session["workspace_id"], status, deal_id)}


@router.get("/dashboard")
async def dashboard(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.promise_dashboard(db, session["workspace_id"])


@router.get("/contradictions")
async def contradictions(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"contradictions": svc.detect_contradictions(db, session["workspace_id"])}


@router.get("/expiring")
async def expiring(within_days: int = Query(30, ge=1), session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"promises": svc.get_expiring_promises(db, session["workspace_id"], within_days)}


@router.get("/{promise_id}")
async def get_one(promise_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    result = svc.get_promise(db, promise_id)
    if not result:
        raise HTTPException(status_code=404)
    return result


@router.get("/{promise_id}/coverage")
async def coverage(promise_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    result = svc.promise_coverage(db, promise_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{promise_id}/map-controls")
async def map_controls(promise_id: int, body: MapControlsBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.map_promise_to_controls(db, promise_id, body.control_ids)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result
