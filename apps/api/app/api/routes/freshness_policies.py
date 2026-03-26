"""Evidence freshness policies API (P1-43)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import freshness_policy_service as svc

router = APIRouter(prefix="/freshness-policies", tags=["freshness-policies"])


class PolicyBody(BaseModel):
    source_type: str
    max_age_days: int
    warn_before_days: int = 14


@router.post("")
async def set_policy(body: PolicyBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.set_policy(db, session["workspace_id"], body.source_type, body.max_age_days, body.warn_before_days)
    db.commit()
    return result


@router.get("")
async def list_policies(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"policies": svc.get_policies(db, session["workspace_id"])}


@router.get("/effective")
async def effective(source_type: str = Query(...), session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.get_effective_policy(db, session["workspace_id"], source_type)


@router.get("/evaluate")
async def evaluate(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"results": svc.evaluate_freshness(db, session["workspace_id"])}


@router.delete("/{source_type}")
async def delete_policy(source_type: str, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    if not svc.delete_policy(db, session["workspace_id"], source_type):
        raise HTTPException(status_code=404)
    db.commit()
    return {"deleted": True}
