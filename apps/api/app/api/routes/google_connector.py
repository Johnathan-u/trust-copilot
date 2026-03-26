"""Google Workspace connector API (P1-27, P1-28, P1-29)."""

from fastapi import APIRouter, Depends, Query

from app.core.auth_deps import require_can_admin
from app.services import google_workspace_collector_service as gw

router = APIRouter(prefix="/connectors/google", tags=["google-connector"])


@router.get("/users")
async def collect_users(domain: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return gw.collect_users(domain)


@router.get("/mfa")
async def collect_mfa(domain: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return gw.collect_mfa_enrollment(domain)


@router.get("/admin-roles")
async def collect_admin_roles(domain: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return gw.collect_admin_roles(domain)


@router.post("/sync")
async def sync(domain: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return gw.run_google_sync(session["workspace_id"], domain)
