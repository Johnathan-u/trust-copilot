"""Alerting engine API (P1-37)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import alerting_engine_service as svc

router = APIRouter(prefix="/alerting-engine", tags=["alerting-engine"])


@router.get("/drift")
async def drift(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"alerts": svc.check_drift_alerts(db, session["workspace_id"])}


@router.get("/connectors")
async def connectors(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"alerts": svc.check_connector_failure_alerts(db, session["workspace_id"])}


@router.get("/stale-evidence")
async def stale(staleness_days: int = Query(90, ge=1), session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"alerts": svc.check_stale_evidence_alerts(db, session["workspace_id"], staleness_days)}


@router.get("/all")
async def all_alerts(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.run_all_checks(db, session["workspace_id"])


@router.get("/email-digest")
async def email_digest(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    return svc.generate_email_digest(db, session["workspace_id"])
