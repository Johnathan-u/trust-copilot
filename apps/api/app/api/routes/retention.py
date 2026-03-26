"""Evidence retention and archiving API (P1-51)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import retention_service as svc

router = APIRouter(prefix="/retention", tags=["retention"])


class PolicyBody(BaseModel):
    retention_days: int = 365
    archive_after_days: int | None = None
    auto_delete: bool = False
    source_type: str | None = None


@router.post("/policies")
async def set_policy(body: PolicyBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.set_policy(db, session["workspace_id"], body.retention_days, body.archive_after_days, body.auto_delete, body.source_type)
    db.commit()
    return result


@router.get("/policies")
async def list_policies(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"policies": svc.get_policies(db, session["workspace_id"])}


@router.get("/evaluate")
async def evaluate(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    return svc.evaluate_retention(db, session["workspace_id"])


@router.post("/archive")
async def archive(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.run_archival(db, session["workspace_id"])
    db.commit()
    return result


@router.post("/delete")
async def delete(dry_run: bool = Query(True), session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.run_deletion(db, session["workspace_id"], dry_run=dry_run)
    if not dry_run:
        db.commit()
    return result
