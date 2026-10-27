"""GitHub connector API (P1-23, P1-24, P1-25)."""

from fastapi import APIRouter, Depends, Query

from app.core.auth_deps import require_can_admin
from app.api.credential_lifecycle_api import register_fixed
from app.services import github_collector_service as gh

router = APIRouter(prefix="/connectors/github", tags=["github-connector"])


@router.get("/repos")
async def collect_repos(org: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return gh.collect_repos(org, workspace_id=session["workspace_id"])


@router.get("/access")
async def collect_access(org: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return gh.collect_access(org, workspace_id=session["workspace_id"])


@router.get("/protection")
async def collect_protection(
    org: str | None = Query(None), session: dict = Depends(require_can_admin)
):
    return gh.collect_branch_protection(org, workspace_id=session["workspace_id"])


@router.post("/sync")
async def sync(org: str | None = Query(None), session: dict = Depends(require_can_admin)):
    return gh.run_github_sync(session["workspace_id"], org)


register_fixed(
    router,
    source_type="github",
    credential_type="personal_token",
    prefix="github",
)
