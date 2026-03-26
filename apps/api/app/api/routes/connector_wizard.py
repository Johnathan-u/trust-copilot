"""Connector setup wizard API (P1-15)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import connector_wizard_service as svc

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
async def start_setup(body: SetupBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.start_setup(db, session["workspace_id"], body.connector_type)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.post("/validate")
async def validate_setup(body: SetupBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.validate_setup(db, session["workspace_id"], body.connector_type)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.post("/disable")
async def disable(body: SetupBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.disable_connector(db, session["workspace_id"], body.connector_type)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    db.commit()
    return result
