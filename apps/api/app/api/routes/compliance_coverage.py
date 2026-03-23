"""Compliance Coverage API — single endpoint for the coverage dashboard."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth_deps import require_can_review

router = APIRouter(prefix="/compliance-coverage")


@router.get("")
def get_coverage(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_review),
):
    from app.services.compliance_coverage import get_compliance_coverage

    workspace_id = request.state.workspace_id
    return get_compliance_coverage(db, workspace_id)
