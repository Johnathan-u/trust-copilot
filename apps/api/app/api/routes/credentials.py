"""Credential store API — admin-only encrypted credential management."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.credential_lifecycle_api import (
    CredentialMaterialBody,
    commit_if_needed,
    run_connect,
    run_revoke,
    run_rotate,
    run_verify,
)
from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import credential_store_service as cs
from app.services.credential_lifecycle.scopes import canonical_source, default_credential_type

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
    workspace_id = session["workspace_id"]
    return {
        "credentials": cs.list_credentials(db, workspace_id),
        "observation_contract": cs.list_observation_contract(workspace_id),
    }


@router.post("")
async def store_credential(
    req: StoreCredentialRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    if not req.value.strip():
        raise HTTPException(status_code=400, detail="Value is required")
    result = cs.store_credential(
        db,
        session["workspace_id"],
        req.source_type,
        req.credential_type,
        req.value,
        rotation_interval_days=req.rotation_interval_days,
        expires_at=req.expires_at,
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


def _declared_source(body: CredentialMaterialBody) -> tuple[str, str]:
    if not body.source_type:
        raise HTTPException(status_code=400, detail="source_type is required")
    source = canonical_source(body.source_type)
    return source, body.credential_type or default_credential_type(source)


@router.post("/connect", operation_id="credentials_connect")
async def connect_credential(
    request: Request,
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source, cred_type = _declared_source(body)
    result = run_connect(
        db,
        request,
        session,
        body,
        source_type=source,
        credential_type=cred_type,
        route_name="credentials.connect",
    )
    commit_if_needed(db)
    return result


@router.post("/verify", operation_id="credentials_verify")
async def verify_credential(
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source, cred_type = _declared_source(body)
    result = run_verify(db, session, source_type=source, credential_type=cred_type)
    commit_if_needed(db)
    return result


@router.get("/{credential_id}", operation_id="credentials_get")
async def get_credential(
    credential_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    rows = cs.list_credentials(db, session["workspace_id"])
    for row in rows:
        if row["id"] == credential_id:
            return row
    raise HTTPException(status_code=404, detail="Credential not found")


@router.post("/{credential_id}/rotate", operation_id="credentials_rotate")
async def rotate_credential(
    credential_id: int,
    request: Request,
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = run_rotate(
        db,
        request,
        session,
        body,
        source_type=body.source_type or "credential",
        credential_type=body.credential_type or "api_token",
        route_name="credentials.rotate",
        credential_id=credential_id,
    )
    commit_if_needed(db)
    return result


@router.post("/{credential_id}/revoke", operation_id="credentials_revoke")
async def revoke_credential_by_id(
    credential_id: int,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = run_revoke(
        db,
        request,
        session,
        source_type="credential",
        credential_type="api_token",
        route_name="credentials.revoke",
        credential_id=credential_id,
    )
    commit_if_needed(db)
    return result
