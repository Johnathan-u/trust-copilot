"""Shareable spaces API (P1-66, P1-70, TC-17-005b)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.documents import stream_stored_document
from app.core.auth_deps import _resolve_permission, require_can_admin, require_session
from app.core.database import get_db
from app.services import shareable_space_service as ss
from app.services.storage import StorageClient, get_storage

# One body for a missing object and an object the share link does not list.
LISTED_OBJECT_MISSING = "Not found"
_LIST_FIELDS = ("article_ids", "answer_ids", "document_ids")

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


class UpdateSpaceListsBody(BaseModel):
    article_ids: list[int] | None = None
    answer_ids: list[int] | None = None
    document_ids: list[int] | None = None


def _asset_lists(body: UpdateSpaceListsBody) -> dict[str, list[int]]:
    """Fields the caller sent. An explicit null clears that list."""
    lists: dict[str, list[int]] = {}
    for field in _LIST_FIELDS:
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        lists[field] = [] if value is None else value
    return lists


@router.post("")
async def create_space(
    body: CreateSpaceBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
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
    except ss.ListedAssetNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
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


@router.patch("/{space_id}")
async def update_space_lists(
    space_id: int,
    body: UpdateSpaceListsBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Replace asset lists on a space in this workspace.

    A missing id and an id from another workspace are the same 404, and the
    saved lists stay as they were. Another workspace's space is 404 as well.
    The raw token is not returned.
    """
    try:
        result = ss.update_space_lists(
            db,
            space_id,
            workspace_id=session["workspace_id"],
            lists=_asset_lists(body),
        )
    except ss.ListedAssetNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


def _live_space(db: Session, token: str):
    space = ss.live_space_for_token(db, token)
    if space is None:
        raise HTTPException(status_code=404, detail=LISTED_OBJECT_MISSING)
    return space


@router.get("/access")
async def access_space(
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Public endpoint to access a shareable space by token."""
    return ss.access_space_by_token(db, token)


@router.get("/access/documents/{document_id}/content")
async def access_document_content(
    document_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
    storage: StorageClient = Depends(get_storage),
):
    """Original bytes for a document listed on this live space.

    An unlisted id, a deleted document, and a document from another workspace
    are the same 404. This does not accept a reviewer session in place of the
    token, and the reviewer content route does not accept this token.
    """
    space = _live_space(db, token)
    document = ss.granted_document(db, space, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=LISTED_OBJECT_MISSING)
    return stream_stored_document(document, storage)


@router.get("/access/articles/{article_id}")
async def access_article(
    article_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Read one article listed on this live space."""
    space = _live_space(db, token)
    article = ss.granted_article(db, space, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail=LISTED_OBJECT_MISSING)
    return {"id": article.id, "title": article.title, "content": article.content}


@router.get("/access/answers/{answer_id}")
async def access_answer(
    answer_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Read one answer listed on this live space. Citations are not included."""
    space = _live_space(db, token)
    answer = ss.granted_answer(db, space, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail=LISTED_OBJECT_MISSING)
    return {"id": answer.id, "text": answer.text, "status": answer.status}
