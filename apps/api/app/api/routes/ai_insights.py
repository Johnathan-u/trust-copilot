"""AI Insights endpoint — powers the AI Insights dashboard."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services.ai_insights import get_ai_insights

router = APIRouter(prefix="/ai-insights", tags=["ai-insights"])


@router.get("")
def ai_insights(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_admin),
):
    workspace_id = request.state.workspace_id
    return get_ai_insights(db, workspace_id)
