"""Auth dependencies for workspace isolation (OPS-02) and RBAC (AUTH-205)."""

import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.mfa import mfa_reenrol_pending, mfa_reenrol_required
from app.core.roles import BUILTIN_ROLES, can_admin, can_edit, can_export, can_review
from app.core.session import verify_token
from app.models import ApiKey, CustomRole, UserMfa, UserSession, Workspace, WorkspaceMember

SESSION_COOKIE = "tc_session"
DEFAULT_SESSION_MAX_AGE_SECONDS = 86400 * 7
_MFA_ENROL_ROUTES = frozenset(
    {
        ("GET", "/api/auth/me"),
        ("GET", "/api/auth/mfa/status"),
        ("GET", "/api/auth/sessions"),
        ("POST", "/api/auth/mfa/setup"),
        ("POST", "/api/auth/mfa/confirm"),
        ("POST", "/api/auth/logout"),
    }
)
_PENDING_ACCOUNT_ROUTES = frozenset(
    {
        ("GET", "/api/auth/me"),
        ("GET", "/api/auth/sessions"),
        ("GET", "/api/auth/alerts"),
        ("POST", "/api/auth/sessions/revoke-others"),
        ("POST", "/api/auth/change-password"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/auth/mfa/status"),
        ("POST", "/api/auth/mfa/setup"),
        ("POST", "/api/auth/mfa/confirm"),
        ("POST", "/api/auth/mfa/disable"),
        ("POST", "/api/auth/switch-workspace"),
        ("GET", "/api/workspaces/creation-policy"),
        ("POST", "/api/workspaces"),
    }
)


def get_session(request: Request) -> dict | None:
    """Return session payload from cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = verify_token(token)
    if (
        session
        and session.get("mfa_enrol_only")
        and (request.method, request.url.path) not in _MFA_ENROL_ROUTES
    ):
        return None
    return session


def workspace_session_max_age_seconds(db: Session, workspace_id: int) -> int:
    """Read the current tenant cap; workspace zero is account-only onboarding."""
    if workspace_id == 0:
        return DEFAULT_SESSION_MAX_AGE_SECONDS
    try:
        workspace = (
            db.query(Workspace).filter(Workspace.id == workspace_id).populate_existing().first()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Session policy unavailable") from exc
    if workspace is None:
        raise HTTPException(status_code=403, detail="Active workspace membership required")
    age = workspace.session_max_age_seconds
    return int(age) if age is not None and age > 0 else DEFAULT_SESSION_MAX_AGE_SECONDS


def enforce_session_record(session: dict, db: Session) -> float:
    """Validate the owned row and return its absolute, currently permitted deadline."""
    user_id = session.get("user_id")
    if not user_id:
        # Preserve the existing denial for a cookie with no human identity.
        # API keys use their separate authenticated branch and never enter here.
        raise HTTPException(status_code=403, detail="Active workspace membership required")
    if type(user_id) is not int or user_id < 1:
        raise HTTPException(status_code=401, detail="Session invalidated")
    row = (
        db.query(UserSession)
        .filter(
            UserSession.session_id == session.get("session_id"),
            UserSession.user_id == user_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=401, detail="Session invalidated")
    try:
        created = row.created_at
        created = (
            created.replace(tzinfo=timezone.utc)
            if created.tzinfo is None
            else created.astimezone(timezone.utc)
        )
        now = datetime.now(timezone.utc)
        if created > now:
            raise ValueError("Future session creation")
        age = workspace_session_max_age_seconds(db, session.get("workspace_id"))
        deadline = created + timedelta(seconds=age)
    except (AttributeError, OverflowError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Session invalidated") from exc
    if now >= deadline:
        raise HTTPException(status_code=401, detail="Session expired")
    return min(deadline.timestamp(), session["exp"])


def enforce_mfa_enrol_session(request: Request, session: dict, db: Session) -> None:
    """Keep the administrator-reset flow restricted, including old normal cookies."""
    uid = session.get("user_id")
    if not uid:
        return
    factor = db.query(UserMfa).filter(UserMfa.user_id == uid).first()
    pending = bool(factor and mfa_reenrol_pending(factor.totp_secret_encrypted))
    if factor and mfa_reenrol_required(factor.totp_secret_encrypted):
        raise HTTPException(status_code=403, detail="MFA requires an administrator reset")
    if pending and not session.get("mfa_enrol_only"):
        raise HTTPException(status_code=403, detail="Sign in again to complete MFA enrollment")
    if session.get("mfa_enrol_only"):
        if not pending or not session.get("session_id"):
            raise HTTPException(status_code=401, detail="MFA enrollment session expired")
        if (request.method, request.url.path) not in _MFA_ENROL_ROUTES:
            raise HTTPException(status_code=403, detail="Complete MFA enrollment first")
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == uid,
                WorkspaceMember.workspace_id == session.get("workspace_id"),
            )
            .first()
        )
        if not member or member.suspended:
            raise HTTPException(status_code=403, detail="Active workspace membership required")


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


def resolve_current_membership(request: Request, session: dict, db: Session) -> dict:
    """Resolve human workspace authority after credential and MFA validation."""
    uid, wid = session.get("user_id"), session.get("workspace_id")
    if not uid:
        raise HTTPException(status_code=403, detail="Active workspace membership required")
    if wid == 0 and session.get("role") == "pending":
        # The existing onboarding credential has account authority only. Never
        # treat workspace zero as membership or let it reach tenant operations.
        if (request.method, request.url.path) not in _PENDING_ACCOUNT_ROUTES:
            raise HTTPException(status_code=403, detail="Complete workspace setup first")
        return session
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == wid)
        .populate_existing()
        .first()
    )
    if member is None:
        raise HTTPException(status_code=403, detail="Active workspace membership required")
    if member.suspended:
        raise HTTPException(
            status_code=403, detail="Your account has been suspended in this workspace"
        )
    # MFA enrollment stays account-only even when the current member is admin.
    return {**session, "role": "mfa_enrol" if session.get("mfa_enrol_only") else member.role}


async def require_session(request: Request, db: Session = Depends(get_db)) -> dict:
    """Dependency: require valid session or valid API key, or raise 401."""
    api_ctx = get_api_key_context(request, db)
    if api_ctx is not None:
        _set_request_workspace_id(request, api_ctx.get("workspace_id"))
        return api_ctx
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    enforce_session_record(session, db)
    enforce_mfa_enrol_session(request, session, db)
    session = resolve_current_membership(request, session, db)
    _set_request_workspace_id(request, session.get("workspace_id"))
    return session


async def require_valid_session(request: Request, db: Session = Depends(get_db)) -> dict:
    """Alias for require_session (same behavior)."""
    return await require_session(request, db)


async def require_valid_session_optional(
    request: Request, db: Session = Depends(get_db)
) -> dict | None:
    """Return session or API key context if present; else None. Use for routes that allow optional auth."""
    try:
        return await require_session(request, db)
    except HTTPException:
        return None


def _resolve_permission(
    role: str | None, permission_name: str, workspace_id: int | None, db: Session
) -> bool:
    """Check permission for built-in or custom role. Custom roles are looked up from DB."""
    if role in BUILTIN_ROLES:
        fn = {
            "can_edit": can_edit,
            "can_review": can_review,
            "can_export": can_export,
            "can_admin": can_admin,
        }
        return fn.get(permission_name, lambda _: False)(role)
    if not role or not workspace_id:
        return False
    try:
        cr = (
            db.query(CustomRole)
            .filter(
                CustomRole.workspace_id == workspace_id,
                CustomRole.name == role,
            )
            .first()
        )
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
