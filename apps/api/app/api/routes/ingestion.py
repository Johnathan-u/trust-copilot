"""Ingestion pipeline API (P1-16)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import ingestion_pipeline_service as ips

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


class IngestBody(BaseModel):
    source_type: str
    title: str
    source_metadata: str | None = None
    document_id: int | None = None


class IngestBatchBody(BaseModel):
    source_type: str
    items: list[dict]


@router.post("")
async def ingest(
    body: IngestBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ips.ingest_evidence(
        db, session["workspace_id"], body.source_type, body.title,
        body.source_metadata, body.document_id,
    )
    db.commit()
    return result


@router.post("/batch")
async def ingest_batch(
    body: IngestBatchBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ips.ingest_batch(db, session["workspace_id"], body.source_type, body.items)
    db.commit()
    return result


@router.get("/stats")
async def ingestion_stats(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return ips.get_ingestion_stats(db, session["workspace_id"])
