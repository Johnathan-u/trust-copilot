"""Connector setup wizard API (P1-15)."""

from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import connector_wizard_service as svc
from app.services.credential_lifecycle.scopes import canonical_source, default_credential_type

router = APIRouter(prefix="/connector-wizard", tags=["connector-wizard"])


class SetupBody(BaseModel):
    connector_type: str


@router.get("/catalog")
async def catalog(session: dict = Depends(require_session)):
    return {"connectors": svc.get_catalog()}


@router.get("/catalog/{connector_type}")
async def connector_details(connector_type: str, session: dict = Depends(require_session)):
    result = svc.get_connector_details(connector_type)
    if not result:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {connector_type}")
    return result


@router.post("/start")
async def start_setup(
    body: SetupBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)
):
    result = svc.start_setup(db, session["workspace_id"], body.connector_type)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.post("/validate")
async def validate_setup(
    body: SetupBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)
):
    result = svc.validate_setup(db, session["workspace_id"], body.connector_type)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.post("/disable")
async def disable(
    body: SetupBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)
):
    result = svc.disable_connector(db, session["workspace_id"], body.connector_type)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    db.commit()
    return result


def _wizard_source(body: CredentialMaterialBody) -> tuple[str, str]:
    name = body.connector_type or body.source_type
    if not name:
        raise HTTPException(status_code=400, detail="connector_type is required")
    source = canonical_source(name)
    return source, body.credential_type or default_credential_type(source)


@router.post("/connect", operation_id="wizard_connect_credential")
async def connect_credential(
    request: Request,
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source, cred_type = _wizard_source(body)
    result = run_connect(
        db,
        request,
        session,
        body,
        source_type=source,
        credential_type=cred_type,
        route_name="wizard.connect",
    )
    commit_if_needed(db)
    return result


@router.post("/verify", operation_id="wizard_verify_credential")
async def verify_credential(
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source, cred_type = _wizard_source(body)
    result = run_verify(db, session, source_type=source, credential_type=cred_type)
    commit_if_needed(db)
    return result


@router.post("/rotate", operation_id="wizard_rotate_credential")
async def rotate_credential(
    request: Request,
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source, cred_type = _wizard_source(body)
    result = run_rotate(
        db,
        request,
        session,
        body,
        source_type=source,
        credential_type=cred_type,
        route_name="wizard.rotate",
    )
    commit_if_needed(db)
    return result


@router.post("/revoke", operation_id="wizard_revoke_credential")
async def revoke_credential(
    request: Request,
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source, cred_type = _wizard_source(body)
    result = run_revoke(
        db,
        request,
        session,
        source_type=source,
        credential_type=cred_type,
        route_name="wizard.revoke",
    )
    commit_if_needed(db)
    return result
