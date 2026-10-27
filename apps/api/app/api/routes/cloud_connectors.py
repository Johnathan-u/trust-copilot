"""Cloud connector packs API (P2-103 GCP, P2-104 Azure, P2-105 GitLab, P2-106 Okta, P2-107 HRIS)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
from app.services import cloud_connector_service as cc
from app.services.credential_lifecycle.scopes import (
    CLOUD_SOURCES,
    canonical_source,
    default_credential_type,
)

router = APIRouter(prefix="/connectors/cloud", tags=["cloud-connectors"])


@router.get("/gcp")
async def collect_gcp(
    project_id: str | None = Query(None), session: dict = Depends(require_can_admin)
):
    return cc.collect_gcp(project_id, workspace_id=session["workspace_id"])


@router.get("/azure")
async def collect_azure(
    tenant_id: str | None = Query(None), session: dict = Depends(require_can_admin)
):
    return cc.collect_azure(tenant_id, workspace_id=session["workspace_id"])


@router.get("/gitlab")
async def collect_gitlab(
    group: str | None = Query(None), session: dict = Depends(require_can_admin)
):
    return cc.collect_gitlab(group, workspace_id=session["workspace_id"])


@router.get("/okta")
async def collect_okta(
    domain: str | None = Query(None), session: dict = Depends(require_can_admin)
):
    return cc.collect_okta(domain, workspace_id=session["workspace_id"])


@router.get("/hris")
async def collect_hris(
    provider: str | None = Query(None), session: dict = Depends(require_can_admin)
):
    return cc.collect_hris(provider, workspace_id=session["workspace_id"])


@router.post("/sync/{connector}")
async def sync(connector: str, session: dict = Depends(require_can_admin)):
    result = cc.run_connector_sync(session["workspace_id"], connector)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


def _cloud_source(connector: str) -> str:
    source = canonical_source(connector)
    if source not in CLOUD_SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {connector}")
    return source


@router.post("/{connector}/connect", operation_id="cloud_connect_credential")
async def connect_cloud(
    connector: str,
    request: Request,
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source = _cloud_source(connector)
    result = run_connect(
        db,
        request,
        session,
        body,
        source_type=source,
        credential_type=default_credential_type(source),
        route_name="cloud.connect",
    )
    commit_if_needed(db)
    return result


@router.post("/{connector}/verify", operation_id="cloud_verify_credential")
async def verify_cloud(
    connector: str,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source = _cloud_source(connector)
    result = run_verify(
        db,
        session,
        source_type=source,
        credential_type=default_credential_type(source),
    )
    commit_if_needed(db)
    return result


@router.post("/{connector}/rotate", operation_id="cloud_rotate_credential")
async def rotate_cloud(
    connector: str,
    request: Request,
    body: CredentialMaterialBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source = _cloud_source(connector)
    result = run_rotate(
        db,
        request,
        session,
        body,
        source_type=source,
        credential_type=default_credential_type(source),
        route_name="cloud.rotate",
    )
    commit_if_needed(db)
    return result


@router.post("/{connector}/revoke", operation_id="cloud_revoke_credential")
async def revoke_cloud(
    connector: str,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    source = _cloud_source(connector)
    result = run_revoke(
        db,
        request,
        session,
        source_type=source,
        credential_type=default_credential_type(source),
        route_name="cloud.revoke",
    )
    commit_if_needed(db)
    return result
