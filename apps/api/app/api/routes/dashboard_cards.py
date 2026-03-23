"""Admin-configurable workspace dashboard cards API."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.models.dashboard_card import (
    ALLOWED_ICONS,
    ALLOWED_ROUTES,
    CARD_SIZES,
    VISIBILITY_SCOPES,
    DashboardCard,
)

router = APIRouter(prefix="/dashboard/cards", tags=["dashboard-cards"])


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
    {"title": "Documents", "description": "Upload and manage evidence documents.", "icon": "document", "target_route": "/dashboard/documents", "visibility_scope": "all", "size": "medium", "is_builtin": True},
    {"title": "Questionnaires", "description": "Import and parse customer questionnaires.", "icon": "questionnaire", "target_route": "/dashboard/questionnaires", "visibility_scope": "all", "size": "medium", "is_builtin": True},
    {"title": "Exports", "description": "Export completed answers to XLSX or DOCX.", "icon": "export", "target_route": "/dashboard/exports", "visibility_scope": "all", "size": "medium", "is_builtin": True},
    {"title": "Trust Center", "description": "Manage trust articles and what customers see.", "icon": "trust", "target_route": "/dashboard/trust-center", "visibility_scope": "all", "size": "medium", "is_builtin": True},
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
        from app.core.roles import can_admin
        from app.models import CustomRole
        role = session.get("role")
        wid = session.get("workspace_id")
        if role and wid:
            cr = db.query(CustomRole).filter(CustomRole.workspace_id == wid, CustomRole.name == role).first()
            if cr and getattr(cr, "can_admin", False):
                is_admin = True

    result = list(DEFAULT_CARDS)

    if is_admin:
        result += [{**_card_dict(c), "is_builtin": False} for c in custom_rows]
    else:
        result += [
            {**_card_dict(c), "is_builtin": False} for c in custom_rows
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


@router.post("")
@router.post("/")
def create_card(
    body: CardCreate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create a new dashboard card for the workspace."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")

    if body.target_route not in ALLOWED_ROUTES:
        raise HTTPException(status_code=422, detail=f"Invalid target_route. Allowed: {ALLOWED_ROUTES}")
    if body.icon not in ALLOWED_ICONS:
        raise HTTPException(status_code=422, detail=f"Invalid icon. Allowed: {ALLOWED_ICONS}")
    if body.visibility_scope not in VISIBILITY_SCOPES:
        raise HTTPException(status_code=422, detail=f"Invalid visibility_scope. Allowed: {list(VISIBILITY_SCOPES)}")
    if body.size not in CARD_SIZES:
        raise HTTPException(status_code=422, detail=f"Invalid size. Allowed: {list(CARD_SIZES)}")

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
    db.commit()
    db.refresh(card)

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
    return _card_dict(card)


class CardUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    icon: str | None = Field(None, max_length=32)
    target_route: str | None = Field(None, max_length=256)
    visibility_scope: str | None = Field(None, max_length=16)
    size: str | None = Field(None, max_length=16)
    is_enabled: bool | None = None


@router.patch("/{card_id}")
def update_card(
    card_id: int,
    body: CardUpdate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update a dashboard card. Admin only, workspace-scoped."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")

    card = db.query(DashboardCard).filter(
        DashboardCard.id == card_id,
        DashboardCard.workspace_id == ws,
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Dashboard card not found")

    changes = {}
    if body.title is not None:
        card.title = body.title
        changes["title"] = body.title
    if body.description is not None:
        card.description = body.description
        changes["description"] = body.description
    if body.icon is not None:
        if body.icon not in ALLOWED_ICONS:
            raise HTTPException(status_code=422, detail=f"Invalid icon. Allowed: {ALLOWED_ICONS}")
        card.icon = body.icon
        changes["icon"] = body.icon
    if body.target_route is not None:
        if body.target_route not in ALLOWED_ROUTES:
            raise HTTPException(status_code=422, detail=f"Invalid target_route. Allowed: {ALLOWED_ROUTES}")
        card.target_route = body.target_route
        changes["target_route"] = body.target_route
    if body.visibility_scope is not None:
        if body.visibility_scope not in VISIBILITY_SCOPES:
            raise HTTPException(status_code=422, detail=f"Invalid visibility_scope. Allowed: {list(VISIBILITY_SCOPES)}")
        card.visibility_scope = body.visibility_scope
        changes["visibility_scope"] = body.visibility_scope
    if body.size is not None:
        if body.size not in CARD_SIZES:
            raise HTTPException(status_code=422, detail=f"Invalid size. Allowed: {list(CARD_SIZES)}")
        card.size = body.size
        changes["size"] = body.size
    if body.is_enabled is not None:
        card.is_enabled = body.is_enabled
        changes["is_enabled"] = body.is_enabled

    card.updated_at = datetime.utcnow()
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

    card = db.query(DashboardCard).filter(
        DashboardCard.id == card_id,
        DashboardCard.workspace_id == ws,
    ).first()
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
        if cid in card_map:
            card_map[cid].sort_order = idx

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
