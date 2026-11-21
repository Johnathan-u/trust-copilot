"""Admin-configurable workspace dashboard cards API."""

import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request  # noqa: F401
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.core.idempotency import (
    IdempotencyKeyError,
    claim as idempotency_claim,
    get as idempotency_get,
    release as idempotency_release,
    scoped_key,
    set as idempotency_set,
)
from app.models.dashboard_card import (
    ALLOWED_ICONS,
    ALLOWED_ROUTES,
    CARD_SIZES,
    VISIBILITY_SCOPES,
    DashboardCard,
)

router = APIRouter(prefix="/dashboard/cards", tags=["dashboard-cards"])

_CREATE_ROUTE = "dashboard-cards:create"
_REQUEST_HASH = "_request_hash"
_STALE_REVISION = "This card changed since it was loaded. Reload it and try again."
_REVISION_REQUIRED = "Send the updated_at value loaded with this card."


def _card_dict(c: DashboardCard) -> dict:
    return {
        "id": c.id,
        "workspace_id": c.workspace_id,
        "title": c.title,
        "description": c.description,
        "icon": c.icon,
        "target_route": c.target_route,
        "sort_order": c.sort_order,
        "is_enabled": c.is_enabled,
        "visibility_scope": c.visibility_scope,
        "size": c.size,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


DEFAULT_CARDS = [
    {
        "title": "Documents",
        "description": "Upload and manage evidence documents.",
        "icon": "document",
        "target_route": "/dashboard/documents",
        "visibility_scope": "all",
        "size": "medium",
        "is_builtin": True,
    },
    {
        "title": "Questionnaires",
        "description": "Import and parse customer questionnaires.",
        "icon": "questionnaire",
        "target_route": "/dashboard/questionnaires",
        "visibility_scope": "all",
        "size": "medium",
        "is_builtin": True,
    },
    {
        "title": "Exports",
        "description": "Export completed answers to XLSX or DOCX.",
        "icon": "export",
        "target_route": "/dashboard/exports",
        "visibility_scope": "all",
        "size": "medium",
        "is_builtin": True,
    },
    {
        "title": "Trust Center",
        "description": "Manage trust articles and what customers see.",
        "icon": "trust",
        "target_route": "/dashboard/trust-center",
        "visibility_scope": "all",
        "size": "medium",
        "is_builtin": True,
    },
]


@router.get("")
@router.get("/")
def list_cards(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Return dashboard cards for the current workspace.

    Built-in default cards are always included first.
    Custom workspace cards are appended after defaults.
    Admins see all custom cards. Non-admins see only enabled custom cards with visibility_scope='all'.
    """
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")

    custom_rows = (
        db.query(DashboardCard)
        .filter(DashboardCard.workspace_id == ws)
        .order_by(DashboardCard.sort_order)
        .all()
    )

    is_admin = session.get("role") in ("admin",)
    if not is_admin:
        from app.core.roles import can_admin  # noqa: F401
        from app.models import CustomRole

        role = session.get("role")
        wid = session.get("workspace_id")
        if role and wid:
            cr = (
                db.query(CustomRole)
                .filter(CustomRole.workspace_id == wid, CustomRole.name == role)
                .first()
            )
            if cr and getattr(cr, "can_admin", False):
                is_admin = True

    result = list(DEFAULT_CARDS)

    if is_admin:
        result += [{**_card_dict(c), "is_builtin": False} for c in custom_rows]
    else:
        result += [
            {**_card_dict(c), "is_builtin": False}
            for c in custom_rows
            if c.is_enabled and c.visibility_scope == "all"
        ]

    return {"cards": result, "has_custom": len(custom_rows) > 0}


class CardCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    icon: str = Field(default="document", max_length=32)
    target_route: str = Field(..., max_length=256)
    visibility_scope: str = Field(default="all", max_length=16)
    size: str = Field(default="medium", max_length=16)
    is_enabled: bool = True


def _create_hash(body: CardCreate) -> str:
    raw = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _idempotency_key(request: Request, workspace_id: int) -> str | None:
    """Optional key scoped to this workspace and the create route. Absent means no claim."""
    names = {name.lower() for name in request.headers.keys()}
    if "idempotency-key" not in names:
        return None
    raw = request.headers.get("Idempotency-Key")
    try:
        key = scoped_key(workspace_id, _CREATE_ROUTE, "new", raw)
    except IdempotencyKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return key or None


def _public_payload(stored: dict) -> dict:
    payload = dict(stored)
    payload.pop(_REQUEST_HASH, None)
    return payload


def _replay(stored: dict, body_hash: str) -> JSONResponse:
    recorded = stored.get(_REQUEST_HASH)
    if isinstance(recorded, str) and recorded != body_hash:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key was already used with a different request body",
        )
    return JSONResponse(content=_public_payload(stored), status_code=200)


def _claim_or_replay(
    db: Session, key: str | None, body_hash: str
) -> tuple[JSONResponse | None, str | None]:
    if not key:
        return None, None
    cached = idempotency_get(db, key)
    if cached:
        return _replay(cached[1], body_hash), None
    owner = idempotency_claim(db, key)
    if owner is None:
        cached_again = idempotency_get(db, key)
        if cached_again:
            return _replay(cached_again[1], body_hash), None
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    return None, owner


def _release_claim(db: Session, key: str | None, owner: str | None) -> None:
    if key and owner:
        idempotency_release(db, key, owner=owner)


def _reject_invalid_card_fields(
    *,
    target_route: str | None = None,
    icon: str | None = None,
    visibility_scope: str | None = None,
    size: str | None = None,
) -> None:
    if target_route is not None and target_route not in ALLOWED_ROUTES:
        raise HTTPException(
            status_code=422, detail=f"Invalid target_route. Allowed: {ALLOWED_ROUTES}"
        )
    if icon is not None and icon not in ALLOWED_ICONS:
        raise HTTPException(status_code=422, detail=f"Invalid icon. Allowed: {ALLOWED_ICONS}")
    if visibility_scope is not None and visibility_scope not in VISIBILITY_SCOPES:
        raise HTTPException(
            status_code=422, detail=f"Invalid visibility_scope. Allowed: {list(VISIBILITY_SCOPES)}"
        )
    if size is not None and size not in CARD_SIZES:
        raise HTTPException(status_code=422, detail=f"Invalid size. Allowed: {list(CARD_SIZES)}")


@router.post("")
@router.post("/")
def create_card(
    body: CardCreate,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create one card. The same Idempotency-Key returns that card.

    A later retry, including one from a new API process, reads the stored
    response and does not insert another row. A failed create releases the key.
    A request with no Idempotency-Key still inserts a new card.
    """
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")

    _reject_invalid_card_fields(
        target_route=body.target_route,
        icon=body.icon,
        visibility_scope=body.visibility_scope,
        size=body.size,
    )
    body_hash = _create_hash(body)
    key = _idempotency_key(request, ws)
    replay, owner = _claim_or_replay(db, key, body_hash)
    if replay is not None:
        return replay
    try:
        max_order = (
            db.query(DashboardCard.sort_order)
            .filter(DashboardCard.workspace_id == ws)
            .order_by(DashboardCard.sort_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order else 0
        card = DashboardCard(
            workspace_id=ws,
            title=body.title,
            description=body.description,
            icon=body.icon,
            target_route=body.target_route,
            sort_order=next_order,
            is_enabled=body.is_enabled,
            visibility_scope=body.visibility_scope,
            size=body.size,
        )
        db.add(card)
        db.flush()
        db.refresh(card)
        payload = _card_dict(card)
        if key and owner:
            idempotency_set(
                db,
                key,
                200,
                {**payload, _REQUEST_HASH: body_hash},
                owner=owner,
                commit=False,
            )
        db.commit()
    except Exception:
        db.rollback()
        _release_claim(db, key, owner)
        raise
    persist_audit(
        db,
        "dashboard.card_created",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=ws,
        resource_type="dashboard_card",
        resource_id=card.id,
        details={"title": card.title, "target_route": card.target_route},
    )
    return payload


class CardUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    icon: str | None = Field(None, max_length=32)
    target_route: str | None = Field(None, max_length=256)
    visibility_scope: str | None = Field(None, max_length=16)
    size: str | None = Field(None, max_length=16)
    is_enabled: bool | None = None
    # The updated_at the editor loaded. It is the row revision, not a new value.
    updated_at: str | None = None


def _loaded_revision(card: DashboardCard) -> str | None:
    if card.updated_at is None:
        return None
    return card.updated_at.isoformat()


def _require_loaded_revision(card: DashboardCard, loaded: str | None) -> None:
    """409 when the caller does not still hold the row's updated_at.

    The check runs before any column is written. A missing value is 422.
    Built-in cards are not rows and never reach this function.
    """
    if loaded is None or not loaded.strip():
        raise HTTPException(status_code=422, detail=_REVISION_REQUIRED)
    if loaded.strip() != _loaded_revision(card):
        raise HTTPException(status_code=409, detail=_STALE_REVISION)


@router.patch("/{card_id}")
def update_card(
    card_id: int,
    body: CardUpdate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update a dashboard card. Admin only, workspace-scoped.

    ``updated_at`` must be the value the editor loaded. A mismatch is 409 and
    the stored row is left unchanged. The write also requires that value in
    the UPDATE, so a second writer who loaded the same revision cannot commit.
    """
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")

    card = (
        db.query(DashboardCard)
        .filter(
            DashboardCard.id == card_id,
            DashboardCard.workspace_id == ws,
        )
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="Dashboard card not found")

    _require_loaded_revision(card, body.updated_at)
    _reject_invalid_card_fields(
        target_route=body.target_route,
        icon=body.icon,
        visibility_scope=body.visibility_scope,
        size=body.size,
    )

    changes: dict[str, object] = {}
    values: dict[str, object] = {}
    if body.title is not None:
        values["title"] = body.title
        changes["title"] = body.title
    if body.description is not None:
        values["description"] = body.description
        changes["description"] = body.description
    if body.icon is not None:
        values["icon"] = body.icon
        changes["icon"] = body.icon
    if body.target_route is not None:
        values["target_route"] = body.target_route
        changes["target_route"] = body.target_route
    if body.visibility_scope is not None:
        values["visibility_scope"] = body.visibility_scope
        changes["visibility_scope"] = body.visibility_scope
    if body.size is not None:
        values["size"] = body.size
        changes["size"] = body.size
    if body.is_enabled is not None:
        values["is_enabled"] = body.is_enabled
        changes["is_enabled"] = body.is_enabled

    expected = card.updated_at
    values["updated_at"] = datetime.utcnow()
    stmt = (
        update(DashboardCard)
        .where(
            DashboardCard.id == card.id,
            DashboardCard.workspace_id == ws,
        )
        .values(**values)
    )
    if expected is None:
        stmt = stmt.where(DashboardCard.updated_at.is_(None))
    else:
        stmt = stmt.where(DashboardCard.updated_at == expected)
    result = db.execute(stmt)
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail=_STALE_REVISION)
    db.commit()
    db.refresh(card)

    persist_audit(
        db,
        "dashboard.card_updated",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=ws,
        resource_type="dashboard_card",
        resource_id=card.id,
        details=changes,
    )
    return _card_dict(card)


@router.delete("/{card_id}")
def delete_card(
    card_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Delete a dashboard card. Admin only, workspace-scoped."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")

    card = (
        db.query(DashboardCard)
        .filter(
            DashboardCard.id == card_id,
            DashboardCard.workspace_id == ws,
        )
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="Dashboard card not found")

    card_info = {"title": card.title, "target_route": card.target_route}
    db.delete(card)
    db.commit()

    persist_audit(
        db,
        "dashboard.card_deleted",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=ws,
        resource_type="dashboard_card",
        resource_id=card_id,
        details=card_info,
    )
    return {"ok": True}


class ReorderRequest(BaseModel):
    card_ids: list[int]


@router.post("/reorder")
def reorder_cards(
    body: ReorderRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Reorder dashboard cards. Admin only.

    Accepts a list of card IDs in desired order. Cards not listed keep their position.
    """
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")

    cards = (
        db.query(DashboardCard)
        .filter(DashboardCard.workspace_id == ws, DashboardCard.id.in_(body.card_ids))
        .all()
    )
    card_map = {c.id: c for c in cards}

    for idx, cid in enumerate(body.card_ids):
        card = card_map.get(cid)
        if card is not None and card.sort_order != idx:
            card.sort_order = idx
            card.updated_at = datetime.utcnow()

    db.commit()

    persist_audit(
        db,
        "dashboard.layout_reordered",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=ws,
        resource_type="dashboard_card",
        details={"order": body.card_ids},
    )
    return {"ok": True}


@router.get("/allowed-routes")
def get_allowed_routes(
    session: dict = Depends(require_can_admin),
):
    """Return list of allowed target routes and icons for card configuration."""
    return {
        "routes": ALLOWED_ROUTES,
        "icons": ALLOWED_ICONS,
        "sizes": list(CARD_SIZES),
        "visibility_scopes": list(VISIBILITY_SCOPES),
    }
