"""Vendor risk: send questionnaire to vendor (TC-R-B6)."""

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.models import VendorRequest
from app.models.vendor_request import VENDOR_REQUEST_STATUSES

router = APIRouter(prefix="/vendor-requests", tags=["vendor-requests"])


class VendorRequestCreate(BaseModel):
    vendor_email: str
    questionnaire_id: int | None = None


def _to_dict(v: VendorRequest) -> dict:
    return {
        "id": v.id,
        "workspace_id": v.workspace_id,
        "vendor_email": v.vendor_email,
        "questionnaire_id": v.questionnaire_id,
        "status": v.status,
        "link_token": v.link_token,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.get("/")
@router.get("")
def list_vendor_requests(
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List vendor requests for workspace."""
    ws = session.get("workspace_id")
    if ws is None:
        return []
    rows = db.query(VendorRequest).filter(VendorRequest.workspace_id == ws).order_by(VendorRequest.created_at.desc()).all()
    return [_to_dict(r) for r in rows]


@router.post("/")
def create_vendor_request(
    body: VendorRequestCreate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create a vendor request; generates a shareable link token. Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    email = (body.vendor_email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="vendor_email is required")
    link_token = secrets.token_urlsafe(32)
    v = VendorRequest(
        workspace_id=ws,
        vendor_email=email,
        questionnaire_id=body.questionnaire_id,
        status="sent",
        link_token=link_token,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    d = _to_dict(v)
    # Frontend can build share URL from this
    d["share_url"] = f"/vendor-response?token={link_token}"
    return d
