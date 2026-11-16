"""Shareable spaces API (P1-66, P1-70)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import _resolve_permission, require_can_admin, require_session
from app.core.database import get_db
from app.services import shareable_space_service as ss

router = APIRouter(prefix="/shareable-spaces", tags=["shareable-spaces"])


class CreateSpaceBody(BaseModel):
    name: str
    buyer_company: str | None = None
    buyer_email: str | None = None
    opportunity_id: str | None = None
    description: str | None = None
    article_ids: list[int] | None = None
    answer_ids: list[int] | None = None
    document_ids: list[int] | None = None
    expires_days: int = 30


@router.post("")
async def create_space(
    body: CreateSpaceBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ss.create_space(
        db,
        session["workspace_id"],
        body.name,
        session["user_id"],
        buyer_company=body.buyer_company,
        buyer_email=body.buyer_email,
        opportunity_id=body.opportunity_id,
        description=body.description,
        article_ids=body.article_ids,
        answer_ids=body.answer_ids,
        document_ids=body.document_ids,
        expires_days=body.expires_days,
    )
    db.commit()
    return result


def _caller_can_admin(session: dict, db: Session) -> bool:
    """Same bar as require_can_admin, without denying the list or detail read."""
    return _resolve_permission(session.get("role"), "can_admin", session.get("workspace_id"), db)


@router.get("")
async def list_spaces(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {
        "spaces": ss.list_spaces(
            db,
            session["workspace_id"],
            include_admin_indicator=_caller_can_admin(session, db),
        )
    }


@router.post("/{space_id}/deactivate")
async def deactivate(
    space_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ss.deactivate_space(db, space_id, workspace_id=session["workspace_id"])
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/{space_id}/rotate")
async def rotate_space(
    space_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Issue a new token for a live space. Another workspace is a 404.

    Inactive and expired spaces are 409 and are left unchanged. 409 matches
    other state refusals: the row exists, and this action does not apply.
    """
    try:
        result = ss.rotate_space(db, space_id, workspace_id=session["workspace_id"])
    except ss.RotationRefused as refused:
        raise HTTPException(status_code=409, detail=refused.detail) from refused
    if not result:
        raise HTTPException(status_code=404)
    return result


@router.get("/access")
async def access_space(
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Public endpoint to access a shareable space by token."""
    return ss.access_space_by_token(db, token)
