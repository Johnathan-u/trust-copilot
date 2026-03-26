"""Feature flag management API — admin only."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import feature_flags as ff_service

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


class SetFlagRequest(BaseModel):
    flag_name: str
    enabled: bool


class SeedResponse(BaseModel):
    created: int


@router.get("")
async def list_flags(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """List all feature flags with resolved state for the current workspace."""
    workspace_id = session["workspace_id"]
    return {"flags": ff_service.get_all_flags(db, workspace_id)}


@router.get("/{flag_name}")
async def get_flag(
    flag_name: str,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Check if a specific feature flag is enabled."""
    workspace_id = session["workspace_id"]
    enabled = ff_service.is_enabled(db, workspace_id, flag_name)
    default, description = ff_service.KNOWN_FLAGS.get(flag_name, (False, ""))
    return {
        "flag_name": flag_name,
        "enabled": enabled,
        "description": description,
    }


@router.patch("")
async def set_flag(
    req: SetFlagRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Set a feature flag for the current workspace."""
    workspace_id = session["workspace_id"]
    flag_name = req.flag_name.strip().lower()
    if not flag_name or len(flag_name) > 128:
        raise HTTPException(status_code=400, detail="Invalid flag name")
    result = ff_service.set_flag(db, workspace_id, flag_name, req.enabled)
    return result


@router.post("/seed")
async def seed_defaults(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Seed all known default flags for the current workspace (skip existing)."""
    workspace_id = session["workspace_id"]
    created = ff_service.seed_defaults(db, workspace_id)
    return {"created": created}
