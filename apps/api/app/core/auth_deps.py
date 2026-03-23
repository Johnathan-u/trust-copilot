"""Auth dependencies for workspace isolation (OPS-02) and RBAC (AUTH-205)."""

import hashlib
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.roles import BUILTIN_ROLES, can_admin, can_edit, can_export, can_review
from app.core.session import verify_token
from app.models import ApiKey, CustomRole, UserSession, WorkspaceMember

SESSION_COOKIE = "tc_session"


def get_session(request: Request) -> dict | None:
    """Return session payload from cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return verify_token(token)


def get_api_key_context(request: Request, db: Session) -> dict | None:
    """If Authorization: Bearer <key> is valid, return session-like dict (workspace_id, role, etc.). Else None."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    raw = auth[7:].strip()
    if not raw or len(raw) > 512:
        return None
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    row = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not row:
        return None
    from datetime import datetime
    if row.expires_at and row.expires_at <= datetime.utcnow():
        return None
    return {
        "workspace_id": row.workspace_id,
        "role": row.role,
        "user_id": None,
        "email": "api-key",
        "session_id": None,
    }


def _set_request_workspace_id(request: Request, workspace_id: int | None) -> None:
    """Set request.state.workspace_id for logging. Never raise — avoid 500s from state assignment."""
    try:
        if hasattr(request, "state"):
            request.state.workspace_id = workspace_id
    except Exception:
        pass


async def require_session(request: Request, db: Session = Depends(get_db)) -> dict:
    """Dependency: require valid session or valid API key, or raise 401."""
    api_ctx = get_api_key_context(request, db)
    if api_ctx is not None:
        _set_request_workspace_id(request, api_ctx.get("workspace_id"))
        return api_ctx
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session_id = session.get("session_id")
    if session_id:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        if not row:
            raise HTTPException(status_code=401, detail="Session invalidated")
    _set_request_workspace_id(request, session.get("workspace_id"))
    uid = session.get("user_id")
    wid = session.get("workspace_id")
    if uid and wid:
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == uid,
            WorkspaceMember.workspace_id == wid,
        ).first()
        if mem and mem.suspended:
            raise HTTPException(status_code=403, detail="Your account has been suspended in this workspace")
    return session


async def require_valid_session(request: Request, db: Session = Depends(get_db)) -> dict:
    """Alias for require_session (same behavior)."""
    return await require_session(request, db)


async def require_valid_session_optional(request: Request, db: Session = Depends(get_db)) -> dict | None:
    """Return session or API key context if present; else None. Use for routes that allow optional auth."""
    api_ctx = get_api_key_context(request, db)
    if api_ctx is not None:
        _set_request_workspace_id(request, api_ctx.get("workspace_id"))
        return api_ctx
    session = get_session(request)
    if not session:
        return None
    session_id = session.get("session_id")
    if session_id:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        if not row:
            return None
    _set_request_workspace_id(request, session.get("workspace_id"))
    return session


def _resolve_permission(role: str | None, permission_name: str, workspace_id: int | None, db: Session) -> bool:
    """Check permission for built-in or custom role. Custom roles are looked up from DB."""
    if role in BUILTIN_ROLES:
        fn = {"can_edit": can_edit, "can_review": can_review, "can_export": can_export, "can_admin": can_admin}
        return fn.get(permission_name, lambda _: False)(role)
    if not role or not workspace_id:
        return False
    try:
        cr = db.query(CustomRole).filter(
            CustomRole.workspace_id == workspace_id,
            CustomRole.name == role,
        ).first()
        if not cr:
            return False
        return bool(getattr(cr, permission_name, False))
    except Exception:
        return False


def _require_permission(permission_fn, permission_name: str):
    """Return a dependency that requires session and the given permission (403 if denied)."""

    async def _dep(request: Request, db: Session = Depends(get_db)) -> dict:
        session = await require_session(request, db)
        role = session.get("role")
        wid = session.get("workspace_id")
        if not _resolve_permission(role, permission_name, wid, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return session

    return _dep


# RBAC dependencies: use these in routes that need a specific permission (AUTH-205).
require_can_edit = _require_permission(can_edit, "can_edit")
require_can_review = _require_permission(can_review, "can_review")
require_can_export = _require_permission(can_export, "can_export")
require_can_admin = _require_permission(can_admin, "can_admin")


