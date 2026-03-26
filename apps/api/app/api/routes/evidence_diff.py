"""Evidence diff viewer API (P1-45)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import evidence_diff_service as ed

router = APIRouter(prefix="/evidence-diff", tags=["evidence-diff"])


@router.get("/snapshots/{control_id}")
async def diff_snapshots(
    control_id: int,
    snapshot_a: int | None = Query(None),
    snapshot_b: int | None = Query(None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return ed.diff_control_snapshots(db, session["workspace_id"], control_id, snapshot_a, snapshot_b)


@router.get("/evidence/{control_id}")
async def diff_evidence(
    control_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return ed.diff_evidence_items(db, session["workspace_id"], control_id)
