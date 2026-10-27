"""Demo proof package API.

Schema version 1 adds proof_summary and origin/basis/window labels.
Legacy keys sample_questionnaire, coverage_report, gap_list, walkthrough
and live_stats remain. New failures use the ApiError fields
code, message, request_id, retryable and optional field_errors.
Existing 401 and suspended-member 403 responses keep their current detail text.
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.models import Workspace, WorkspaceMember
from app.services.demo_proof_service import (
    SummaryUnreadable,
    WindowError,
    _build_coverage_report,
    _build_gap_list,
    _build_sample_questionnaire,
    _build_walkthrough,
    generate_demo_package,
    load_summary,
    parse_window,
)

# api_keys.role is the only scope field. "read" is the read scope.
# editor, reviewer, admin and custom roles are not read-scoped.
READ_SCOPED_API_KEY_ROLE = "read"

router = APIRouter(prefix="/demo-proof", tags=["demo-proof"])


def _api_error(
    status: int,
    code: str,
    message: str,
    request: Request,
    *,
    retryable: bool = False,
    field_errors: dict | None = None,
) -> JSONResponse:
    request_id = getattr(getattr(request, "state", None), "request_id", None) or str(uuid.uuid4())
    body = {
        "code": code,
        "message": message,
        "request_id": request_id,
        "retryable": retryable,
    }
    if field_errors:
        body["field_errors"] = field_errors
    return JSONResponse(status_code=status, content=body)


def _guard(request: Request, db: Session, session: dict, workspace_id: int | None):
    """Recheck current membership. Reject a workspace id that is not the session workspace."""
    session_workspace = session.get("workspace_id")
    if workspace_id is not None and workspace_id != session_workspace:
        return _api_error(
            403,
            "workspace_mismatch",
            "The workspace in the request does not match the current session.",
            request,
        )
    if not session_workspace:
        return _api_error(
            403,
            "not_a_member",
            "This session is not a member of a workspace.",
            request,
        )
    workspace = db.get(Workspace, session_workspace)
    if workspace is None:
        return _api_error(
            403,
            "not_a_member",
            "This session is not a member of a workspace.",
            request,
        )
    user_id = session.get("user_id")
    if user_id is None:
        # Workspace mismatch was already rejected. A key may read only its own
        # workspace, and only when the key itself is read-scoped.
        if session.get("role") != READ_SCOPED_API_KEY_ROLE:
            return _api_error(
                403,
                "api_key_not_read_scoped",
                "A workspace API key can read this summary only when it is read-scoped.",
                request,
            )
        return None
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == session_workspace,
        )
        .first()
    )
    if member is None or member.suspended:
        return _api_error(
            403,
            "not_a_member",
            "This session is not a current member of the workspace.",
            request,
        )
    return None


@router.get("")
async def get_demo_package(
    request: Request,
    window_start: str | None = Query(default=None),
    window_end: str | None = Query(default=None),
    workspace_id: int | None = Query(default=None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Full package. Reads stored rows and does not write a snapshot."""
    blocked = _guard(request, db, session, workspace_id)
    if blocked is not None:
        return blocked
    try:
        start, end = parse_window(window_start, window_end)
    except WindowError as exc:
        return _api_error(
            400,
            "invalid_window",
            exc.message,
            request,
            field_errors={exc.field: exc.message},
        )
    try:
        return generate_demo_package(
            db,
            session["workspace_id"],
            user_id=session.get("user_id"),
            window_start=start,
            window_end=end,
            persist=False,
        )
    except SummaryUnreadable:
        return _api_error(
            500,
            "summary_unreadable",
            "The stored summary could not be read. It was not replaced with a new figure.",
            request,
            retryable=True,
        )


@router.post("")
async def save_demo_package(
    request: Request,
    window_start: str | None = Query(default=None),
    window_end: str | None = Query(default=None),
    workspace_id: int | None = Query(default=None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Store a snapshot for the caller's workspace and return that package.

    This is the only demo-proof route that writes. The write is one snapshot
    row for the session workspace. It does not change evidence rows and it
    does not write another workspace.
    """
    blocked = _guard(request, db, session, workspace_id)
    if blocked is not None:
        return blocked
    try:
        start, end = parse_window(window_start, window_end)
    except WindowError as exc:
        return _api_error(
            400,
            "invalid_window",
            exc.message,
            request,
            field_errors={exc.field: exc.message},
        )
    try:
        return generate_demo_package(
            db,
            session["workspace_id"],
            user_id=session.get("user_id"),
            window_start=start,
            window_end=end,
            persist=True,
        )
    except SummaryUnreadable:
        return _api_error(
            500,
            "summary_unreadable",
            "The stored summary could not be read. It was not replaced with a new figure.",
            request,
            retryable=True,
        )


@router.get("/summaries/{summary_id}")
async def get_persisted_summary(
    summary_id: int,
    request: Request,
    workspace_id: int | None = Query(default=None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Read one persisted snapshot. A snapshot from another workspace is not found."""
    blocked = _guard(request, db, session, workspace_id)
    if blocked is not None:
        return blocked
    try:
        summary = load_summary(db, session["workspace_id"], summary_id)
    except SummaryUnreadable:
        return _api_error(
            500,
            "summary_unreadable",
            "The stored summary could not be read. It was not replaced with a new figure.",
            request,
            retryable=True,
        )
    if summary is None:
        return _api_error(
            404,
            "summary_not_found",
            "No demonstration summary with that id is stored for this workspace.",
            request,
        )
    return summary


@router.get("/questionnaire")
async def get_sample_questionnaire(
    request: Request,
    workspace_id: int | None = Query(default=None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Synthetic sample questionnaire. Not stored evidence and not commercial traction."""
    blocked = _guard(request, db, session, workspace_id)
    if blocked is not None:
        return blocked
    return _build_sample_questionnaire()


@router.get("/coverage")
async def get_coverage_report(
    request: Request,
    workspace_id: int | None = Query(default=None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Coverage figures for the synthetic sample only."""
    blocked = _guard(request, db, session, workspace_id)
    if blocked is not None:
        return blocked
    return _build_coverage_report(_build_sample_questionnaire())


@router.get("/gaps")
async def get_gap_list(
    request: Request,
    workspace_id: int | None = Query(default=None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Gap list for the synthetic sample only."""
    blocked = _guard(request, db, session, workspace_id)
    if blocked is not None:
        return blocked
    return _build_gap_list(_build_sample_questionnaire())


@router.get("/walkthrough")
async def get_walkthrough(
    request: Request,
    workspace_id: int | None = Query(default=None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Synthetic walkthrough. Step text is not evidence."""
    blocked = _guard(request, db, session, workspace_id)
    if blocked is not None:
        return blocked
    return _build_walkthrough()
