"""Workspace settings API (ENT-202)."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.config import SIGNUP_POLICY_SELF_SIGNUP, get_settings
from app.core.database import get_db
from app.core.rate_limit import (
    RateLimitBackendError,
    is_rate_limited,
    record_attempt,
    retry_after_seconds,
)
from app.core.session import is_production_env, sign_session
from app.models import User, Workspace, WorkspaceMember
from app.services.answer_generation import resolve_model

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

SESSION_COOKIE = "tc_session"
SESSION_MAX_AGE = 86400 * 7


def _session_cookie_kwargs(max_age: int) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": is_production_env(),
        "max_age": max_age,
    }


class CreateWorkspaceBody(BaseModel):
    name: str


# TC-04-001a: who may create a workspace, how many they may administer, and how often.
_ADMIN_ROLES = ("owner", "admin")
_CREATE_WINDOW_SEC = 3600.0
_CREATE_DENIED = "Workspace creation is not available for this account."
_CREATE_CAP_REACHED = "This account has reached its workspace limit."
_CREATE_THROTTLED = "Too many workspaces created recently. Try again later."
_CREATE_UNAVAILABLE = "Workspace creation is temporarily unavailable. Try again later."
_CREATE_UNAVAILABLE_RETRY_AFTER = "60"


def _is_deployment_operator(user: User, settings) -> bool:
    """Host-configured operator account; requires a verified email."""
    email = (user.email or "").strip().lower()
    return bool(user.email_verified) and email in settings.deployment_operator_emails


def _may_create_workspace(db: Session, user: User, settings) -> bool:
    """Signup policy: invitation-only allows active owners/admins and deployment operators;
    self-signup additionally allows any email-verified user."""
    if _is_deployment_operator(user, settings):
        return True
    is_active_admin = (
        db.query(WorkspaceMember.id)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.role.in_(_ADMIN_ROLES),
            WorkspaceMember.suspended.is_(False),
        )
        .first()
        is not None
    )
    if is_active_admin:
        return True
    return settings.signup_policy == SIGNUP_POLICY_SELF_SIGNUP and bool(user.email_verified)


def _admin_membership_count(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(WorkspaceMember.id))
        .filter(WorkspaceMember.user_id == user_id, WorkspaceMember.role.in_(_ADMIN_ROLES))
        .scalar()
        or 0
    )


@router.post("")
async def create_workspace(
    body: CreateWorkspaceBody,
    request: Request,
    response: Response,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Create a new workspace; current user becomes admin (B3). Reissues session cookie with new workspace context.

    Subject to the signup policy (403), a per-user hourly throttle (429 with
    Retry-After) and a per-user cap on owner/admin memberships (409)."""
    user_id = session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    settings = get_settings()
    # Lock the user row so concurrent requests cannot both pass the cap check.
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not _may_create_workspace(db, user, settings):
        raise HTTPException(status_code=403, detail=_CREATE_DENIED)
    rate_key = f"workspace_create:user:{user_id}"
    per_hour = settings.workspace_create_per_hour
    # Production fails closed if the shared store errors. Other limiter callers stay fail-open.
    try:
        limited = is_rate_limited(
            rate_key,
            max_attempts=per_hour,
            window_sec=_CREATE_WINDOW_SEC,
            fail_closed=is_production_env(),
        )
    except RateLimitBackendError:
        raise HTTPException(
            status_code=503,
            detail=_CREATE_UNAVAILABLE,
            headers={"Retry-After": _CREATE_UNAVAILABLE_RETRY_AFTER},
        )
    if limited:
        raise HTTPException(
            status_code=429,
            detail=_CREATE_THROTTLED,
            headers={"Retry-After": str(retry_after_seconds(rate_key, _CREATE_WINDOW_SEC))},
        )
    name = (body.name or "").strip()
    if not name or len(name) > 255:
        raise HTTPException(status_code=400, detail="Name required (max 255 chars)")
    if _admin_membership_count(db, user_id) >= settings.workspace_admin_cap_per_user:
        raise HTTPException(status_code=409, detail=_CREATE_CAP_REACHED)
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
    record_attempt(rate_key, max_attempts=per_hour, window_sec=_CREATE_WINDOW_SEC)
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
            key=SESSION_COOKIE,
            value=token,
            **_session_cookie_kwargs(SESSION_MAX_AGE),
        )
    return {"id": ws.id, "name": ws.name, "slug": ws.slug}


@router.get("/creation-policy")
async def workspace_creation_policy(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Whether the signed-in user passes the same signup-policy gate as POST /api/workspaces.

    The path is ``creation-policy`` so it sits next to workspace creation and is not a
    slug. The cap and the hourly throttle are not part of this boolean: POST still
    returns 409 or 429 for those. The body is only ``can_create_workspace``.
    """
    user_id = session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"can_create_workspace": _may_create_workspace(db, user, get_settings())}


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
            ws.session_max_age_seconds = min(
                body.session_max_age_seconds, 86400 * 90
            )  # cap 90 days
    if body.ai_completion_model is not None:
        raw = body.ai_completion_model.strip() or None
        ws.ai_completion_model = resolve_model(raw) if raw else None
    if body.ai_temperature is not None:
        ws.ai_temperature = max(0.0, min(body.ai_temperature, 1.5))
    if (
        body.ai_automate_everything is not None
        and getattr(ws, "ai_automate_everything", False) != body.ai_automate_everything
    ):
        ws.ai_automate_everything = body.ai_automate_everything
        from app.core.audit import persist_audit

        action = "automation.enabled" if body.ai_automate_everything else "automation.disabled"
        persist_audit(
            db,
            action,
            user_id=session.get("user_id"),
            workspace_id=workspace_id,
            details={"ai_automate_everything": body.ai_automate_everything},
        )
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
