"""Credential store API — admin-only encrypted credential management."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import credential_store_service as cs

router = APIRouter(prefix="/credentials", tags=["credentials"])


class StoreCredentialRequest(BaseModel):
    source_type: str
    credential_type: str
    value: str
    rotation_interval_days: int | None = None
    expires_at: datetime | None = None


@router.get("")
async def list_credentials(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"credentials": cs.list_credentials(db, session["workspace_id"])}


@router.post("")
async def store_credential(
    req: StoreCredentialRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    if not req.value.strip():
        raise HTTPException(status_code=400, detail="Value is required")
    result = cs.store_credential(
        db, session["workspace_id"], req.source_type, req.credential_type,
        req.value, rotation_interval_days=req.rotation_interval_days, expires_at=req.expires_at,
    )
    db.commit()
    return result


@router.delete("/{source_type}/{credential_type}")
async def revoke_credential(
    source_type: str,
    credential_type: str,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    if not cs.revoke_credential(db, session["workspace_id"], source_type, credential_type):
        raise HTTPException(status_code=404, detail="Credential not found")
    db.commit()
    return {"revoked": True}


@router.get("/rotation-due")
async def rotation_due(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"credentials": cs.check_rotation_due(db, session["workspace_id"])}


@router.get("/expiring")
async def expiring_soon(
    days: int = Query(7, ge=1, le=90),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"credentials": cs.check_expiring(db, session["workspace_id"], days_ahead=days)}
