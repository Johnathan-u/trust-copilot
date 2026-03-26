"""Customer-ready export pack API — branded cover, summary, evidence bundle."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import export_pack_service

router = APIRouter(prefix="/export-pack", tags=["export-pack"])


@router.get("")
async def get_full_pack(
    questionnaire_id: int = Query(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Generate the full customer-ready export pack for a questionnaire."""
    workspace_id = session["workspace_id"]
    try:
        return export_pack_service.generate_full_pack(db, workspace_id, questionnaire_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/cover")
async def get_cover_page(
    questionnaire_id: int = Query(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Generate the branded cover page for a questionnaire export."""
    workspace_id = session["workspace_id"]
    try:
        return export_pack_service.generate_cover_page(db, workspace_id, questionnaire_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/summary")
async def get_executive_summary(
    questionnaire_id: int = Query(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Generate the executive summary for a questionnaire export."""
    workspace_id = session["workspace_id"]
    try:
        return export_pack_service.generate_executive_summary(db, workspace_id, questionnaire_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/evidence")
async def get_evidence_bundle(
    questionnaire_id: int = Query(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Generate the evidence bundle manifest for a questionnaire export."""
    workspace_id = session["workspace_id"]
    try:
        return export_pack_service.generate_evidence_bundle(db, workspace_id, questionnaire_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
