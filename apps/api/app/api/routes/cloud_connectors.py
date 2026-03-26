"""Cloud connector packs API (P2-103 GCP, P2-104 Azure, P2-105 GitLab, P2-106 Okta, P2-107 HRIS)."""

from fastapi import APIRouter, Depends, Query

from app.core.auth_deps import require_can_admin
from app.services import cloud_connector_service as cc

router = APIRouter(prefix="/connectors/cloud", tags=["cloud-connectors"])


@router.get("/gcp")
async def collect_gcp(project_id: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return cc.collect_gcp(project_id)


@router.get("/azure")
async def collect_azure(tenant_id: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return cc.collect_azure(tenant_id)


@router.get("/gitlab")
async def collect_gitlab(group: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return cc.collect_gitlab(group)


@router.get("/okta")
async def collect_okta(domain: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return cc.collect_okta(domain)


@router.get("/hris")
async def collect_hris(provider: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return cc.collect_hris(provider)


@router.post("/sync/{connector}")
async def sync(connector: str, session: dict = Depends(require_can_admin)):
    result = cc.run_connector_sync(session["workspace_id"], connector)
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=result["error"])
    return result
