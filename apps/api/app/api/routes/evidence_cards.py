"""Evidence cards API (P1-41)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import evidence_cards_service as ec

router = APIRouter(prefix="/evidence-cards", tags=["evidence-cards"])


@router.get("")
async def list_cards(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"cards": ec.get_all_evidence_cards(db, session["workspace_id"])}


@router.get("/{control_id}")
async def get_card(
    control_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    card = ec.get_evidence_card(db, session["workspace_id"], control_id)
    if "error" in card:
        raise HTTPException(status_code=404, detail=card["error"])
    return card
