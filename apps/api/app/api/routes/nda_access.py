"""NDA-gated access request API (P1-65)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import nda_access_service as nda

router = APIRouter(prefix="/nda-access", tags=["nda-access"])


class AccessRequestBody(BaseModel):
    requester_name: str
    requester_email: str
    nda_accepted: bool
    requester_company: str | None = None
    purpose: str | None = None


@router.post("/request")
async def request_access(
    body: AccessRequestBody,
    db: Session = Depends(get_db),
):
    """Public endpoint for buyers to request NDA-gated access."""
    result = nda.request_access(
        db,
        workspace_id=1,
        requester_name=body.requester_name,
        requester_email=body.requester_email,
        nda_accepted=body.nda_accepted,
        requester_company=body.requester_company,
        purpose=body.purpose,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.get("/requests")
async def list_requests(
    status: str | None = Query(None),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"requests": nda.list_requests(db, session["workspace_id"], status)}


@router.post("/approve/{request_id}")
async def approve(
    request_id: int,
    access_days: int = Query(30, ge=1, le=365),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = nda.approve_request(db, request_id, session["user_id"], access_days)
    if not result:
        raise HTTPException(status_code=404, detail="Request not found")
    db.commit()
    return result


@router.post("/reject/{request_id}")
async def reject(
    request_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = nda.reject_request(db, request_id)
    if not result:
        raise HTTPException(status_code=404, detail="Request not found")
    db.commit()
    return result


@router.post("/revoke/{request_id}")
async def revoke(
    request_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = nda.revoke_access(db, request_id)
    if not result:
        raise HTTPException(status_code=404, detail="Request not found")
    db.commit()
    return result


@router.get("/validate")
async def validate_token(
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Public endpoint to validate an access token."""
    return nda.validate_access_token(db, token)
