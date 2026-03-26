"""CRM connector API (E1-02, E1-03)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import crm_connector_service as svc

router = APIRouter(prefix="/crm", tags=["crm"])


@router.post("/sync/salesforce")
async def sync_salesforce(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.sync_salesforce(db, session["workspace_id"])
    db.commit()
    return result


@router.post("/sync/hubspot")
async def sync_hubspot(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.sync_hubspot(db, session["workspace_id"])
    db.commit()
    return result


@router.get("/status")
async def sync_status(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.get_sync_status(db, session["workspace_id"])
