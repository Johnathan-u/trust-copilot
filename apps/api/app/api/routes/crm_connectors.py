"""CRM connector API (E1-02, E1-03, TC-20-050)."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import crm_connector_service as svc
from app.services.salesforce_pipeline_client import SalesforceClientError

router = APIRouter(prefix="/crm", tags=["crm"])

_PIPELINE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SalesforceSyncBody(BaseModel):
    pipeline_id: str
    connection_id: int | None = None

    @field_validator("pipeline_id")
    @classmethod
    def _pipeline(cls, value: str) -> str:
        if not isinstance(value, str) or not _PIPELINE.fullmatch(value):
            raise ValueError("pipeline_id is invalid")
        return value

    @field_validator("connection_id")
    @classmethod
    def _connection(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if type(value) is not int or not 0 < value <= 2147483647:
            raise ValueError("connection_id is invalid")
        return value


@router.post("/sync/salesforce")
async def sync_salesforce(
    body: SalesforceSyncBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
        return svc.enqueue_salesforce_sync(
            db,
            session["workspace_id"],
            pipeline_id=body.pipeline_id,
            connection_id=body.connection_id,
        )
    except SalesforceClientError as exc:
        if exc.code == "config_error":
            raise HTTPException(
                status_code=409, detail="Salesforce pipeline sync is not configured."
            ) from None
        raise HTTPException(
            status_code=422, detail="Salesforce pipeline request was rejected."
        ) from None
    except svc.ConnectionNotFound:
        raise HTTPException(status_code=404, detail="CRM connection not found.") from None
    except svc.PipelineMismatch:
        raise HTTPException(
            status_code=409, detail="CRM connection does not use that pipeline."
        ) from None


@router.post("/sync/hubspot")
async def sync_hubspot(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.sync_hubspot(db, session["workspace_id"])
    db.commit()
    return result


@router.get("/status")
async def sync_status(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.get_sync_status(db, session["workspace_id"])
