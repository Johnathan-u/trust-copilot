"""Compliance Coverage API — single endpoint for the coverage dashboard.

GET stays read-only. A control id is optional. A missing id and an id from
another workspace return the same 404. The workspace totals do not change
when the id is present and found.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth_deps import require_can_review
from app.models.workspace_control import WorkspaceControl

router = APIRouter(prefix="/compliance-coverage")
CONTROL_NOT_FOUND = "Control not found"


@router.get("")
def get_coverage(
    request: Request,
    control_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_can_review),
):
    from app.services.compliance_coverage import get_compliance_coverage

    workspace_id = request.state.workspace_id
    if control_id is not None:
        row = (
            db.query(WorkspaceControl)
            .filter(
                WorkspaceControl.id == control_id,
                WorkspaceControl.workspace_id == workspace_id,
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=CONTROL_NOT_FOUND)
    return get_compliance_coverage(db, workspace_id)
