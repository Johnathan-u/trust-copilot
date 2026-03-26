"""Contract ingestion API (E2-09)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import contract_service as svc

router = APIRouter(prefix="/contracts", tags=["contracts"])


class IngestBody(BaseModel):
    title: str
    original_filename: str | None = None
    body_text: str | None = None


@router.post("/ingest")
async def ingest(body: IngestBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.ingest_contract(
        db, session["workspace_id"], body.title,
        uploaded_by_user_id=session.get("user_id"),
        original_filename=body.original_filename,
        body_text=body.body_text,
    )
    db.commit()
    return result


@router.get("")
async def list_contracts(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"documents": svc.list_contracts(db, session["workspace_id"])}
