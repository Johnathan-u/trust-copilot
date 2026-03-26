"""Trust Center auto-publish API (P1-64)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import trust_center_publish_service as tcp

router = APIRouter(prefix="/trust-center/publish", tags=["trust-center-publish"])


@router.post("")
async def auto_publish(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = tcp.auto_publish_approved_controls(db, session["workspace_id"])
    db.commit()
    return result


@router.get("")
async def list_published(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"articles": tcp.get_published_controls(db, session["workspace_id"])}
