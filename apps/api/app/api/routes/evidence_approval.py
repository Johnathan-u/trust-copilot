"""Evidence approval workflow API (P1-47)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review, require_session
from app.core.database import get_db
from app.services import evidence_approval_service as svc

router = APIRouter(prefix="/evidence-approval", tags=["evidence-approval"])


class RejectBody(BaseModel):
    reason: str | None = None


class BulkApproveBody(BaseModel):
    evidence_ids: list[int]


@router.post("/{evidence_id}/approve")
async def approve(evidence_id: int, session: dict = Depends(require_can_review), db: Session = Depends(get_db)):
    result = svc.approve_evidence(db, evidence_id, session.get("user_id"))
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/{evidence_id}/reject")
async def reject(evidence_id: int, body: RejectBody = RejectBody(), session: dict = Depends(require_can_review), db: Session = Depends(get_db)):
    result = svc.reject_evidence(db, evidence_id, session.get("user_id"), body.reason)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/{evidence_id}/reset")
async def reset(evidence_id: int, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.reset_to_pending(db, evidence_id)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.get("/pending")
async def pending(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"items": svc.get_pending(db, session["workspace_id"])}


@router.get("/approved")
async def approved(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"items": svc.get_approved(db, session["workspace_id"])}


@router.post("/bulk-approve")
async def bulk_approve(body: BulkApproveBody, session: dict = Depends(require_can_review), db: Session = Depends(get_db)):
    result = svc.bulk_approve(db, body.evidence_ids, session.get("user_id"))
    db.commit()
    return result
