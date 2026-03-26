"""Source registry API — manage evidence source types."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import source_registry_service as sr

router = APIRouter(prefix="/sources", tags=["sources"])


class UpdateSourceRequest(BaseModel):
    enabled: bool | None = None
    sync_cadence: str | None = None
    config_json: str | None = None


@router.get("")
async def list_sources(
    enabled_only: bool = Query(False),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    workspace_id = session["workspace_id"]
    return {"sources": sr.list_sources(db, workspace_id, enabled_only=enabled_only)}


@router.get("/health")
async def health_summary(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return sr.get_health_summary(db, session["workspace_id"])


@router.get("/{source_type}")
async def get_source(
    source_type: str,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    src = sr.get_source(db, session["workspace_id"], source_type)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    return src


@router.patch("/{source_type}")
async def update_source(
    source_type: str,
    req: UpdateSourceRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = sr.update_source(db, session["workspace_id"], source_type, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Source not found")
    db.commit()
    return result


@router.post("/seed")
async def seed_sources(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    created = sr.seed_sources(db, session["workspace_id"])
    db.commit()
    return {"created": created}
