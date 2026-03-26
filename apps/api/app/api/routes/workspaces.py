"""Workspace settings API (ENT-202)."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.config import get_settings
from app.core.database import get_db
from app.core.session import sign_session
from app.models import Workspace, WorkspaceMember
from app.services.answer_generation import resolve_model

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

SESSION_COOKIE = "tc_session"
SESSION_MAX_AGE = 86400 * 7


def _session_cookie_kwargs(max_age: int) -> dict:
    s = get_settings()
    return {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": s.app_env == "production",
        "max_age": max_age,
    }


class CreateWorkspaceBody(BaseModel):
    name: str


@router.post("")
async def create_workspace(
    body: CreateWorkspaceBody,
    request: Request,
    response: Response,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Create a new workspace; current user becomes admin (B3). Reissues session cookie with new workspace context."""
    user_id = session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    name = (body.name or "").strip()
    if not name or len(name) > 255:
        raise HTTPException(status_code=400, detail="Name required (max 255 chars)")
    slug = _slug_from_name(name)
    existing = db.query(Workspace).filter(Workspace.slug == slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="A workspace with this name already exists")
    now = datetime.utcnow()
    ws = Workspace(name=name, slug=slug, created_at=now, updated_at=now)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user_id, role="admin"))
    db.commit()
    db.refresh(ws)
    session_id = session.get("session_id")
    if session_id:
        token = sign_session(
            user_id=user_id,
            email=session.get("email", ""),
            workspace_id=ws.id,
            role="admin",
            session_id=session_id,
            max_age_seconds=SESSION_MAX_AGE,
        )
        response.set_cookie(
            key=SESSION_COOKIE, value=token,
            **_session_cookie_kwargs(SESSION_MAX_AGE),
        )
    return {"id": ws.id, "name": ws.name, "slug": ws.slug}


def _slug_from_name(name: str) -> str:
    """Generate URL-safe slug from name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "workspace"


class WorkspaceAuthPolicyUpdate(BaseModel):
    mfa_required: bool | None = None
    session_max_age_seconds: int | None = None
    ai_completion_model: str | None = None
    ai_temperature: float | None = None
    ai_automate_everything: bool | None = None


@router.get("/current")
async def get_current_workspace(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Return current workspace details including auth policy (ENT-202)."""
    workspace_id = session.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="No workspace")
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {
        "id": ws.id,
        "name": ws.name,
        "slug": ws.slug,
        "mfa_required": getattr(ws, "mfa_required", False),
        "session_max_age_seconds": getattr(ws, "session_max_age_seconds", None),
        "ai_completion_model": getattr(ws, "ai_completion_model", None),
        "ai_temperature": getattr(ws, "ai_temperature", None),
        "ai_automate_everything": getattr(ws, "ai_automate_everything", False),
    }


@router.patch("/current")
async def update_current_workspace_policy(
    body: WorkspaceAuthPolicyUpdate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update current workspace auth policy (ENT-202). Admin only."""
    workspace_id = session.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="No workspace")
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if body.mfa_required is not None:
        ws.mfa_required = body.mfa_required
    if body.session_max_age_seconds is not None:
        if body.session_max_age_seconds <= 0:
            ws.session_max_age_seconds = None
        else:
            ws.session_max_age_seconds = min(body.session_max_age_seconds, 86400 * 90)  # cap 90 days
    if body.ai_completion_model is not None:
        raw = body.ai_completion_model.strip() or None
        ws.ai_completion_model = resolve_model(raw) if raw else None
    if body.ai_temperature is not None:
        ws.ai_temperature = max(0.0, min(body.ai_temperature, 1.5))
    if body.ai_automate_everything is not None and getattr(ws, "ai_automate_everything", False) != body.ai_automate_everything:
        ws.ai_automate_everything = body.ai_automate_everything
        from app.core.audit import persist_audit
        action = "automation.enabled" if body.ai_automate_everything else "automation.disabled"
        persist_audit(db, action, user_id=session.get("user_id"), workspace_id=workspace_id,
                      details={"ai_automate_everything": body.ai_automate_everything})
    db.commit()
    db.refresh(ws)
    return {
        "id": ws.id,
        "mfa_required": getattr(ws, "mfa_required", False),
        "session_max_age_seconds": getattr(ws, "session_max_age_seconds", None),
        "ai_completion_model": getattr(ws, "ai_completion_model", None),
        "ai_temperature": getattr(ws, "ai_temperature", None),
        "ai_automate_everything": getattr(ws, "ai_automate_everything", False),
    }


@router.get("/by-slug/{slug}")
def get_workspace_by_slug(
    slug: str,
    db: Session = Depends(get_db),
):
    """Public endpoint: resolve workspace by slug for the public trust page.

    Returns only non-sensitive workspace info (id, name, slug).
    No auth required — this powers the /trust/[slug] public page.
    """
    normalized = slug.strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="Slug is required")
    ws = db.query(Workspace).filter(func.lower(Workspace.slug) == normalized).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"id": ws.id, "name": ws.name, "slug": ws.slug}
