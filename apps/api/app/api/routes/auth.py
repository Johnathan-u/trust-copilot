"""Auth API (AUTH-02, AUTH-03, AUTH-201, AUTH-203, AUTH-204, AUTH-207)."""

import os
import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response

logger = logging.getLogger(__name__)
from fastapi.responses import RedirectResponse

from pydantic import BaseModel
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.audit import audit_log, persist_audit
from app.core.debug_session_log import append_session_debug
from app.core.auth_deps import get_session, require_session, require_valid_session
from app.core.config import get_settings
from app.core.database import get_db
from app.core.mfa import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_totp_secret,
    get_totp_uri,
    verify_totp,
)
from app.core.password import hash_password, verify_password
from app.core.rate_limit import get_client_ip, is_rate_limited, record_attempt
from app.core.session import sign_session, verify_token
from app.models import (
    AuditEvent,
    EmailVerificationToken,
    Invite,
    MfaLoginToken,
    MfaRecoveryCode,
    PasswordResetToken,
    User,
    UserMfa,
    UserOAuthAccount,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.core import roles
from app.core.invite_codes import hash_invite_code
from app.services.email_service import (
    send_password_reset_email,
    send_suspicious_login_email,
    send_verification_code_email,
    send_verification_email,
)
from app.services.oauth_service import (
    generate_state,
    google_authorize_url,
    google_exchange_code,
    github_authorize_url,
    github_exchange_code,
    microsoft_authorize_url,
    microsoft_exchange_code,
)
from app.services.sso_service import (
    idme_authorize_url,
    idme_exchange_code,
    oidc_authorize_url,
    oidc_discover,
    oidc_exchange_code,
)

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "tc_session"
SESSION_MAX_AGE = 86400 * 7  # 7 days default (ENT-202: workspace can override)
# "Remember me" extends cookie/JWT lifetime to at least this many seconds (30 days), capped upward by workspace policy.
REMEMBER_ME_MAX_AGE_SECONDS = 86400 * 30


def _session_cookie_kwargs(max_age: int, persistent: bool = True) -> dict:
    """Secure cookie kwargs: HttpOnly, SameSite=lax, path=/.

    When persistent=True (remember me), max_age is set so the cookie
    survives browser restarts.  When persistent=False, max_age is omitted
    so the browser treats it as a session cookie deleted on close.
    The JWT token inside still has an exp claim for server-side validation.
    """
    s = get_settings()
    kw: dict = {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": s.app_env == "production",
    }
    if persistent:
        kw["max_age"] = max_age
    return kw


def _session_max_age_seconds(db: Session, workspace_id: int) -> int:
    """ENT-202: Per-workspace session lifetime, or default."""
    try:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if ws:
            age = getattr(ws, "session_max_age_seconds", None)
            if age is not None and age > 0:
                return int(age)
    except Exception:
        db.rollback()
    return SESSION_MAX_AGE


def _effective_session_max_age_seconds(db: Session, workspace_id: int, remember_me: bool) -> int:
    """Session cookie max-age: workspace policy, optionally extended for 'remember me'."""
    base = _session_max_age_seconds(db, workspace_id)
    if remember_me:
        return max(base, REMEMBER_ME_MAX_AGE_SECONDS)
    return base


class LoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False


class SwitchWorkspaceRequest(BaseModel):
    workspace_id: int


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    invalidate_other_sessions: bool = False


class AcceptInviteRequest(BaseModel):
    token: str
    password: str | None = None  # Required when accepting as new user (no account yet)


class VerifyInviteCodeRequest(BaseModel):
    email: str
    code: str


class MfaConfirmRequest(BaseModel):
    code: str


class MfaVerifyLoginRequest(BaseModel):
    mfa_token: str
    code: str  # TOTP 6 digits or recovery code
    remember_me: bool = False


class MfaDisableRequest(BaseModel):
    password: str


def _user_response(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name or "User",
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/register")
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """AUTH-207: Register; create user (email_verified=False), send verification code + link."""
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    password = (req.password or "").strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password too short")
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return {"message": "If that email is not yet registered, you will receive a verification code."}
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=(req.display_name or "").strip() or None,
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    code = f"{secrets.randbelow(10**6):06d}"
    code_hash = _token_hash(code)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    evt = EmailVerificationToken(user_id=user.id, token_hash=code_hash, expires_at=expires_at)
    db.add(evt)
    db.commit()
    send_verification_code_email(email, code)
    persist_audit(db, "auth.register", user_id=user.id, email=email)
    return {"message": "If that email is not yet registered, you will receive a verification code."}


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


@router.post("/verify-code")
def verify_code(req: VerifyCodeRequest, db: Session = Depends(get_db)):
    """Verify email using a 6-digit code sent during registration."""
    email = (req.email or "").strip().lower()
    code = (req.code or "").strip()
    if not email or not code:
        raise HTTPException(status_code=400, detail="Email and code are required")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid code")
    if user.email_verified:
        return {"message": "Email already verified."}
    h = _token_hash(code)
    evt = db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.token_hash == h,
    ).first()
    if not evt:
        raise HTTPException(status_code=400, detail="Invalid code")
    now = datetime.now(timezone.utc)
    exp = evt.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        db.delete(evt)
        db.commit()
        raise HTTPException(status_code=400, detail="Code expired. Please register again.")
    user.email_verified = True
    db.delete(evt)
    db.commit()
    persist_audit(db, "auth.email_verified", user_id=user.id, email=user.email)
    return {"message": "Email verified."}


@router.post("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    """AUTH-207: Verify email from link; set user.email_verified=True and delete token."""
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")
    h = _token_hash(token)
    evt = db.query(EmailVerificationToken).filter(EmailVerificationToken.token_hash == h).first()
    if not evt:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    now = datetime.now(timezone.utc)
    exp = evt.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        db.delete(evt)
        db.commit()
        raise HTTPException(status_code=400, detail="Link expired")
    user = db.query(User).filter(User.id == evt.user_id).first()
    if user:
        user.email_verified = True
        db.delete(evt)
        db.commit()
        persist_audit(db, "auth.email_verified", user_id=user.id, email=user.email)
        return {"message": "Email verified. You can sign in."}
    raise HTTPException(status_code=400, detail="Invalid or expired link")


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """AUTH-209: Request password reset. Generic response; send email if account exists."""
    email = (req.email or "").strip().lower()
    ip_key = f"reset:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return {"message": "If that email is registered, you will receive a reset link."}
    record_attempt(ip_key)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).delete(synchronize_session=False)
    token_raw = secrets.token_urlsafe(32)
    token_hash_val = _token_hash(token_raw)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    prt = PasswordResetToken(user_id=user.id, token_hash=token_hash_val, expires_at=expires_at)
    db.add(prt)
    db.commit()
    base = get_settings().frontend_url.rstrip("/")
    reset_url = f"{base}/reset-password?token={token_raw}"
    persist_audit(db, "auth.reset_requested", user_id=user.id, email=email)
    msg = {"message": "If that email is registered, you will receive a reset link."}
    if (
        get_settings().app_env != "production"
        and os.environ.get("TRUST_COPILOT_DEV_RETURN_RESET_URL", "").strip().lower() in ("1", "true", "yes")
    ):
        msg["reset_url"] = reset_url

    _email = email
    def _bg_reset_email():
        try:
            ok = send_password_reset_email(_email, reset_url)
            if not ok:
                logger.warning("Password reset email not accepted for delivery to %s", _email)
        except Exception as exc:
            logger.warning("Password reset email background send failed for %s: %s", _email, exc)

    threading.Thread(target=_bg_reset_email, daemon=True).start()
    return msg


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """AUTH-209: Set new password from token. Do not auto-sign in. Rate limited by IP."""
    ip_key = f"reset_password:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if not req.token or len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Invalid request")
    record_attempt(ip_key)
    h = _token_hash(req.token)
    prt = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == h, PasswordResetToken.used_at.is_(None)).first()
    if not prt:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    now = datetime.now(timezone.utc)
    exp = prt.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        raise HTTPException(status_code=400, detail="Link expired")
    user = db.query(User).filter(User.id == prt.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    user.password_hash = hash_password(req.new_password)
    prt.used_at = now
    db.commit()
    persist_audit(db, "auth.password_reset", user_id=user.id, email=user.email)
    return {"message": "Password updated. You can sign in."}


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    session: dict = Depends(require_valid_session),
    db: Session = Depends(get_db),
):
    """TC-R-B8: Change password for authenticated user. Rate limited; audit; optional revoke other sessions."""
    user_id = session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rate_key = f"change_password:user:{user_id}"
    if is_rate_limited(rate_key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not verify_password(req.current_password, user.password_hash):
        record_attempt(rate_key)
        persist_audit(db, "auth.change_password_failed", user_id=user_id, email=user.email)
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(req.new_password)
    current_sid = session.get("session_id")
    revoked = 0
    if req.invalidate_other_sessions and current_sid:
        revoked = db.query(UserSession).filter(
            UserSession.user_id == user_id,
            UserSession.session_id != current_sid,
        ).delete(synchronize_session=False)
    db.commit()
    persist_audit(
        db,
        "auth.password_changed",
        user_id=user_id,
        email=user.email,
        details={"invalidate_other_sessions": req.invalidate_other_sessions, "revoked": revoked},
    )
    return {"message": "Password updated.", "revoked": revoked}


def _is_db_connection_error(e: Exception) -> bool:
    """True if error is due to DB unreachable/connection (return 503)."""
    if isinstance(e, OperationalError):
        return True
    msg = (getattr(e, "message", None) or str(e)).lower()
    return "connection" in msg or "connect" in msg or "unable to connect" in msg or "refused" in msg


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Session-based login. If MFA enabled, return requires_mfa + mfa_token (AUTH-211). AUTH-210: rate limited."""
    try:
        out = _login_impl(req, request, response, db)
        # #region agent log
        try:
            append_session_debug(
                {
                    "runId": "verify",
                    "hypothesisId": "DB",
                    "location": "auth.py:login",
                    "message": "login_ok",
                    "data": {
                        "requires_mfa": bool(out.get("requires_mfa")),
                        "db_host": urlsplit(get_settings().database_url).hostname,
                    },
                }
            )
        except Exception:
            pass
        # #endregion
        return out
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("auth.login database error: %s", e)
        # #region agent log
        try:
            append_session_debug(
                {
                    "runId": "verify",
                    "hypothesisId": "DB",
                    "location": "auth.py:login",
                    "message": "login_sqlalchemy_error",
                    "data": {
                        "error_class": type(e).__name__,
                        "is_operational": isinstance(e, OperationalError),
                        "snippet": (str(e) or "")[:220],
                        "db_host": urlsplit(get_settings().database_url).hostname,
                    },
                }
            )
        except Exception:
            pass
        # #endregion
        if _is_db_connection_error(e):
            raise HTTPException(status_code=503, detail="Database unavailable. Ensure Postgres is running and DATABASE_URL is correct.")
        raise HTTPException(status_code=500, detail="An error occurred during sign-in. Please try again.")
    except Exception as e:
        logger.exception("auth.login 500: %s", e)
        raise HTTPException(status_code=500, detail="An error occurred during sign-in. Please try again.")


def _login_impl(req: LoginRequest, request: Request, response: Response, db: Session):
    """Inner login logic so we can wrap with try/except for logging."""
    email = (req.email or "").strip().lower()
    password = (req.password or "").strip()
    client_ip = get_client_ip(request)
    ip_key = f"login:ip:{client_ip}"
    email_key = f"login:email:{email}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    if is_rate_limited(email_key):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    record_attempt(ip_key)
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        record_attempt(email_key)
        persist_audit(db, "auth.login_failed")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.workspace_id)
        .first()
    )
    if not member:
        session_id = secrets.token_urlsafe(32)
        db.add(UserSession(
            user_id=user.id,
            session_id=session_id,
            user_agent=request.headers.get("user-agent"),
            ip_address=get_client_ip(request),
        ))
        db.commit()
        max_age = SESSION_MAX_AGE
        token = sign_session(
            user_id=user.id,
            email=user.email,
            workspace_id=0,
            role="pending",
            session_id=session_id,
            max_age_seconds=max_age,
        )
        response.set_cookie(key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age, persistent=False))
        persist_audit(db, "auth.login", user_id=user.id, email=user.email, details={"needs_onboarding": True})
        return {"user": _user_response(user), "needs_onboarding": True}

    mfa_row = db.query(UserMfa).filter(UserMfa.user_id == user.id, UserMfa.enabled.is_(True)).first()
    if mfa_row:
        mfa_token_raw = secrets.token_urlsafe(32)
        mfa_token_hash_val = _token_hash(mfa_token_raw)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        mlt = MfaLoginToken(
            token_hash=mfa_token_hash_val,
            user_id=user.id,
            workspace_id=member.workspace_id,
            role=member.role,
            expires_at=expires_at,
        )
        db.add(mlt)
        db.commit()
        persist_audit(db, "auth.mfa_required", user_id=user.id, email=user.email, workspace_id=member.workspace_id)
        return {"requires_mfa": True, "mfa_token": mfa_token_raw}

    audit_log("auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id)
    try:
        persist_audit(db, "auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id)
    except Exception as e:
        logger.warning("auth.login persist_audit failed (login continues): %s", e)
    session_id = secrets.token_urlsafe(32)
    db.add(UserSession(
        user_id=user.id,
        session_id=session_id,
        user_agent=request.headers.get("user-agent"),
        ip_address=get_client_ip(request),
    ))
    db.commit()
    remember = bool(req.remember_me)
    max_age = _effective_session_max_age_seconds(db, member.workspace_id, remember)
    token = sign_session(
        user_id=user.id,
        email=user.email,
        workspace_id=member.workspace_id,
        role=member.role,
        session_id=session_id,
        max_age_seconds=max_age,
    )
    response.set_cookie(key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age, persistent=remember))
    return {"user": _user_response(user), "workspace_id": member.workspace_id}


@router.post("/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    """Logout - clear session cookie and remove from session store (AUTH-213)."""
    session = get_session(request)
    if session:
        sid = session.get("session_id")
        if sid:
            db.query(UserSession).filter(UserSession.session_id == sid).delete(synchronize_session=False)
            db.commit()
        audit_log(
            "auth.logout",
            user_id=session.get("user_id"),
            email=session.get("email"),
            workspace_id=session.get("workspace_id"),
        )
        persist_audit(
            db,
            "auth.logout",
            user_id=session.get("user_id"),
            email=session.get("email"),
            workspace_id=session.get("workspace_id"),
        )
    _sec = get_settings().app_env == "production"
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax", httponly=True, secure=_sec)
    return {"ok": True}


@router.get("/sessions")
async def list_sessions(session: dict = Depends(require_valid_session), db: Session = Depends(get_db)):
    """AUTH-213: List current user's sessions (device/location)."""
    user_id = session.get("user_id")
    current_sid = session.get("session_id")
    rows = db.query(UserSession).filter(UserSession.user_id == user_id).order_by(UserSession.created_at.desc()).all()
    return {
        "sessions": [
            {
                "id": r.id,
                "session_id": r.session_id[:8] + "…" if r.session_id else None,
                "current": r.session_id == current_sid if current_sid else False,
                "user_agent": r.user_agent,
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(session: dict = Depends(require_valid_session), db: Session = Depends(get_db)):
    """AUTH-213: Invalidate all other sessions for current user; keep current."""
    user_id = session.get("user_id")
    current_sid = session.get("session_id")
    if not current_sid:
        raise HTTPException(status_code=400, detail="Cannot revoke others for legacy session")
    deleted = db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.session_id != current_sid,
    ).delete(synchronize_session=False)
    db.commit()
    persist_audit(db, "auth.sessions_revoked_others", user_id=user_id, email=session.get("email"), details={"count": deleted})
    return {"ok": True, "revoked": deleted}


# ----- ENT-201: OAuth (Google, Microsoft) -----

OAUTH_STATE_COOKIE = "oauth_state"
OAUTH_STATE_MAX_AGE = 600  # 10 min

# Server-side state store so callback works when the state cookie is not sent (e.g. redirect from GitHub)
_oauth_pending_states: dict[str, tuple[str, float]] = {}  # state -> (provider, created_at)


def _oauth_create_signed_state(provider: str) -> str:
    """Create state that can be verified without server-side store (survives API restarts)."""
    payload = {
        "p": provider,
        "n": secrets.token_urlsafe(16),
        "t": int(time.time()),
    }
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(
        get_settings().session_secret.encode(),
        data.encode(),
        "sha256",
    ).hexdigest()
    return f"{data}.{sig}"


def _oauth_verify_signed_state(state: str, expected_provider: str) -> bool:
    """Verify signed state: signature and expiry. No server-side store needed."""
    try:
        data, sig = state.rsplit(".", 1)
        expected = hmac.new(
            get_settings().session_secret.encode(),
            data.encode(),
            "sha256",
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        payload = json.loads(base64.urlsafe_b64decode(data).decode())
        if payload.get("p") != expected_provider:
            return False
        ts = payload.get("t")
        if ts is None or (time.time() - int(ts)) > OAUTH_STATE_MAX_AGE:
            return False
        return True
    except Exception:
        return False


def _oauth_consume_state(state: str, expected_provider: str) -> bool:
    """Validate state from server-side store or cookie; return True if valid. Prunes expired entries."""
    now = time.time()
    # Prune expired
    expired = [s for s, (_, t) in _oauth_pending_states.items() if now - t > OAUTH_STATE_MAX_AGE]
    for s in expired:
        _oauth_pending_states.pop(s, None)
    # Check server-side store first (works when cookie is not sent on redirect)
    entry = _oauth_pending_states.pop(state, None)
    if entry is not None and entry[0] == expected_provider:
        return True
    return False


def _oauth_redirect_uri(provider: str) -> str:
    """Build OAuth callback URL from APP_BASE_URL. Expected paths: .../api/auth/oauth/{provider}/callback."""
    base = get_settings().app_base_url.rstrip("/")
    return f"{base}/api/auth/oauth/{provider}/callback"


def _sso_redirect_uri() -> str:
    """Redirect URI for Enterprise OIDC SSO (ENT-203). Expected path: .../api/auth/sso/callback."""
    base = get_settings().app_base_url.rstrip("/")
    return f"{base}/api/auth/sso/callback"


def _idme_redirect_uri() -> str:
    """ENT-206: Static redirect URI for id.me (no wildcards)."""
    base = get_settings().app_base_url.rstrip("/")
    path = (get_settings().idme_redirect_path or "").strip().lstrip("/")
    return f"{base}/{path}" if path else f"{base}/api/auth/idme/callback"


def _oauth_set_session_and_redirect(user: User, workspace_id: int, role: str, db: Session) -> RedirectResponse:
    session_id = secrets.token_urlsafe(32)
    db.add(UserSession(
        user_id=user.id,
        session_id=session_id,
        user_agent=None,
        ip_address=None,
    ))
    db.commit()
    max_age = _session_max_age_seconds(db, workspace_id)
    token = sign_session(
        user_id=user.id,
        email=user.email,
        workspace_id=workspace_id,
        role=role,
        session_id=session_id,
        max_age_seconds=max_age,
    )
    frontend = get_settings().frontend_url.rstrip("/")
    redirect_url = f"{frontend}/dashboard"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    resp.set_cookie(key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age))
    return resp


@router.get("/oauth/providers")
def oauth_providers():
    """Return which OAuth/SSO providers are configured (for login page buttons). WEB-214: sso when OIDC enabled."""
    s = get_settings()
    oidc_ok = bool(s.oidc_issuer_url and s.oidc_client_id and s.oidc_client_secret)
    return {
        "google": bool(s.oauth_google_client_id and s.oauth_google_client_secret),
        "github": bool(s.oauth_github_client_id and s.oauth_github_client_secret),
        "microsoft": bool(s.oauth_microsoft_client_id and s.oauth_microsoft_client_secret),
        "sso": oidc_ok,
        "idme": bool(s.idme_client_id and s.idme_client_secret),
    }


@router.get("/oauth/redirect-uri")
def oauth_redirect_uri(provider: str = "google"):
    """Return the exact redirect_uri this backend uses for OAuth (for Google Console / debugging)."""
    s = get_settings()
    if provider == "google":
        uri = _oauth_redirect_uri("google")
    elif provider == "github":
        uri = _oauth_redirect_uri("github")
    elif provider == "microsoft":
        uri = _oauth_redirect_uri("microsoft")
    else:
        raise HTTPException(status_code=400, detail="provider must be google, github, or microsoft")
    return {
        "provider": provider,
        "redirect_uri": uri,
        "APP_BASE_URL": s.app_base_url,
    }


@router.get("/oauth/google")
async def oauth_google_start(request: Request, response: Response):
    """Redirect to Google OAuth consent. ENT-201. Uses signed state so callback works even if cookie is lost on redirect."""
    if not get_settings().oauth_google_client_id:
        raise HTTPException(status_code=404, detail="Google OAuth not configured")
    state = _oauth_create_signed_state("google")
    redirect_uri = _oauth_redirect_uri("google")
    url = google_authorize_url(redirect_uri, state)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=f"{state}|google",
        **_session_cookie_kwargs(OAUTH_STATE_MAX_AGE),
    )
    return response


@router.get("/oauth/google/callback")
async def oauth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Handle Google OAuth callback; find or create user, issue session. ENT-201. Accepts signed state or cookie."""
    logger.info("oauth_google_callback entry code=%s state_len=%s", bool(code), len(state) if state else 0, extra={"step": "callback_entry"})
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    ip_key = f"oauth_callback:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    record_attempt(ip_key)
    try:
        return await _oauth_google_callback_impl(request, code, state, db)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("oauth_google_callback database error: %s", e)
        if _is_db_connection_error(e):
            raise HTTPException(status_code=503, detail="Database unavailable. Please try again later.")
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")
    except Exception as e:
        logger.exception("oauth_google_callback 500: %s", e)
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")


async def _oauth_google_callback_impl(request: Request, code: str, state: str, db: Session):
    """Inner Google OAuth callback logic (wrapped by handler for safe 500/503)."""
    state_valid = _oauth_verify_signed_state(state, "google")
    if not state_valid:
        state_valid = _oauth_consume_state(state, "google")
    if not state_valid:
        cookie = request.cookies.get(OAUTH_STATE_COOKIE)
        if cookie and "|" in cookie:
            cookie_state, provider = cookie.strip().split("|", 1)
            if provider == "google" and cookie_state == state:
                state_valid = True
    if not state_valid:
        try:
            persist_audit(db, "auth.oauth_failed", details={"provider": "google", "reason": "invalid_state"})
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Invalid or expired state. Start sign-in from the app login page.")
    redirect_uri = _oauth_redirect_uri("google")
    info = await google_exchange_code(code, redirect_uri)
    if not info:
        logger.warning("oauth_google_callback google_exchange_code returned None")
        try:
            persist_audit(db, "auth.oauth_failed", details={"provider": "google", "reason": "token_exchange_failed"})
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Failed to get user info from Google")
    if not (info.get("provider_user_id") or "").strip():
        logger.warning("oauth_google_callback profile missing user identifier (id/sub)")
        raise HTTPException(status_code=400, detail="Google did not return a user identifier (id or sub)")
    logger.info("oauth_google_callback got profile email_ok=%s", bool(info.get("email")), extra={"step": "after_exchange"})
    # Find linked account or user by email
    oauth_row = db.query(UserOAuthAccount).filter(
        UserOAuthAccount.provider == "google",
        UserOAuthAccount.provider_user_id == info["provider_user_id"],
    ).first()
    if oauth_row:
        user = db.query(User).filter(User.id == oauth_row.user_id).first()
        logger.info("oauth_google_callback linked user_id=%s", user.id if user else None, extra={"step": "user_from_oauth_row"})
    else:
        user = None
        if info.get("email") and info.get("email_verified"):
            user = db.query(User).filter(User.email == info.get("email")).first()
            if user:
                db.add(UserOAuthAccount(
                    user_id=user.id,
                    provider="google",
                    provider_user_id=info["provider_user_id"],
                    email=info.get("email"),
                ))
                db.commit()
                logger.info("oauth_google_callback linked by email user_id=%s", user.id, extra={"step": "user_linked_by_email"})
        elif info.get("email") and not info.get("email_verified"):
            logger.warning("oauth_google_callback email not verified by provider, skipping auto-link for %s", info.get("email")[:3] + "***")
    if not user:
        email = (info.get("email") or "").strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="Google did not provide an email")
        logger.info("oauth_google_callback creating user email=%s", email[:3] + "***" if len(email) > 3 else "***", extra={"step": "user_create_start"})
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=info.get("name"),
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        default_workspace_id = 1
        default_workspace = db.query(Workspace).filter(Workspace.id == default_workspace_id).first()
        if not default_workspace:
            logger.error("oauth_google_callback default workspace id=1 not found; run migrations", extra={"step": "workspace_missing"})
            raise HTTPException(status_code=503, detail="Default workspace not found. Run database migrations.")
        try:
            db.add(WorkspaceMember(workspace_id=default_workspace_id, user_id=user.id, role="editor"))
            db.add(UserOAuthAccount(
                user_id=user.id,
                provider="google",
                provider_user_id=info["provider_user_id"],
                email=email,
            ))
            db.commit()
        except Exception as e:  # noqa: BLE001
            logger.exception("oauth_google_callback user/workspace/oauth create failed: %s", type(e).__name__, extra={"step": "user_create_db"})
            raise
        logger.info("oauth_google_callback created user_id=%s workspace_id=%s", user.id, default_workspace_id, extra={"step": "user_created"})
    member = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.workspace_id).first()
    if not member:
        logger.warning("oauth_google_callback no workspace member user_id=%s", user.id, extra={"step": "no_member"})
        raise HTTPException(status_code=403, detail="No workspace access")
    logger.info("oauth_google_callback member workspace_id=%s role=%s", member.workspace_id, member.role, extra={"step": "workspace_resolved"})
    try:
        persist_audit(db, "auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id, details={"provider": "google"})
    except Exception as e:  # noqa: BLE001
        logger.warning("oauth_google_callback persist_audit failed (login continues): %s", e)
    logger.info("oauth_google_callback setting session redirect", extra={"step": "session_redirect_start"})
    try:
        resp = _oauth_set_session_and_redirect(user, member.workspace_id, member.role, db)
    except Exception as e:  # noqa: BLE001
        logger.exception("oauth_google_callback _oauth_set_session_and_redirect failed: %s", e)
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/", samesite="lax")
    # Log final redirect target only (path), not full URL or cookies
    logger.info("oauth_google_callback success redirect_path=/dashboard", extra={"step": "callback_done"})
    return resp


@router.get("/oauth/github")
async def oauth_github_start(request: Request, response: Response):
    """Redirect to GitHub OAuth consent."""
    s = get_settings()
    if not (s.oauth_github_client_id and s.oauth_github_client_secret):
        raise HTTPException(status_code=404, detail="GitHub OAuth not configured")
    state = _oauth_create_signed_state("github")
    redirect_uri = _oauth_redirect_uri("github")
    url = github_authorize_url(redirect_uri, state)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=f"{state}|github",
        **_session_cookie_kwargs(OAUTH_STATE_MAX_AGE),
    )
    return response


@router.get("/oauth/github/callback")
async def oauth_github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Handle GitHub OAuth callback; find or create user, issue session."""
    logger.info("oauth_github_callback entry", extra={"step": "callback_entry"})
    if not code or not state:
        logger.warning("oauth_github_callback missing code or state", extra={"step": "callback_params"})
        raise HTTPException(status_code=400, detail="Missing code or state")
    ip_key = f"oauth_callback:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    record_attempt(ip_key)
    try:
        return await _oauth_github_callback_impl(request, code, state, db)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("oauth_github_callback database error: %s", e)
        if _is_db_connection_error(e):
            raise HTTPException(status_code=503, detail="Database unavailable. Please try again later.")
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")
    except Exception as e:
        logger.exception("oauth_github_callback 500: %s", e)
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")


async def _oauth_github_callback_impl(request: Request, code: str, state: str, db: Session):
    """Inner GitHub OAuth callback (wrapped by route for safe 500/503)."""
    # Validate state: signed state first (survives API restarts); then in-memory/cookie fallback
    state_valid = _oauth_verify_signed_state(state, "github")
    if not state_valid:
        state_valid = _oauth_consume_state(state, "github")
    if not state_valid:
        cookie = request.cookies.get(OAUTH_STATE_COOKIE)
        if cookie and "|" in cookie:
            cookie_state, provider = cookie.strip().split("|", 1)
            if provider == "github" and cookie_state == state:
                state_valid = True
    if not state_valid:
        try:
            persist_audit(db, "auth.oauth_failed", details={"provider": "github", "reason": "invalid_state"})
        except Exception:
            pass
        logger.warning("oauth_github_callback state invalid or expired", extra={"step": "callback_state"})
        raise HTTPException(status_code=400, detail="Invalid or expired state. Start sign-in from the app login page.")
    logger.info("oauth_github_callback state_ok", extra={"step": "state_valid"})
    redirect_uri = _oauth_redirect_uri("github")
    info = await github_exchange_code(code, redirect_uri)
    if not info or not info.get("provider_user_id"):
        raise HTTPException(status_code=400, detail="Failed to get user info from GitHub")
    logger.info(
        "oauth_github_callback token_ok has_email=%s provider_user_id_len=%s",
        bool(info.get("email")),
        len(info.get("provider_user_id") or ""),
        extra={"step": "token_exchange"},
    )
    oauth_row = db.query(UserOAuthAccount).filter(
        UserOAuthAccount.provider == "github",
        UserOAuthAccount.provider_user_id == info["provider_user_id"],
    ).first()
    if oauth_row:
        user = db.query(User).filter(User.id == oauth_row.user_id).first()
    else:
        user = None
        if info.get("email") and info.get("email_verified"):
            user = db.query(User).filter(User.email == info.get("email")).first()
            if user:
                db.add(UserOAuthAccount(
                    user_id=user.id,
                    provider="github",
                    provider_user_id=info["provider_user_id"],
                    email=info.get("email"),
                ))
                db.commit()
        elif info.get("email") and not info.get("email_verified"):
            logger.warning("oauth_github_callback email not verified by provider, skipping auto-link")
    if not user:
        email = (info.get("email") or "").strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="GitHub did not provide an email (enable user:email scope or set public email)")
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=info.get("name"),
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        default_workspace_id = 1
        default_workspace = db.query(Workspace).filter(Workspace.id == default_workspace_id).first()
        if not default_workspace:
            raise HTTPException(status_code=503, detail="Default workspace not found. Run database migrations.")
        db.add(WorkspaceMember(workspace_id=default_workspace_id, user_id=user.id, role="editor"))
        db.add(UserOAuthAccount(
            user_id=user.id,
            provider="github",
            provider_user_id=info["provider_user_id"],
            email=email,
        ))
        db.commit()
    logger.info("oauth_github_callback user_ok user_id=%s", user.id, extra={"step": "user_resolved"})
    member = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.workspace_id).first()
    if not member:
        raise HTTPException(status_code=403, detail="No workspace access")
    persist_audit(db, "auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id, details={"provider": "github"})
    frontend = get_settings().frontend_url.rstrip("/")
    redirect_url = f"{frontend}/dashboard"
    logger.info(
        "oauth_github_callback session_ok redirect_url=%s",
        redirect_url,
        extra={"step": "redirect_target"},
    )
    resp = _oauth_set_session_and_redirect(user, member.workspace_id, member.role, db)
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/", samesite="lax")
    return resp


@router.get("/oauth/microsoft")
async def oauth_microsoft_start(request: Request, response: Response):
    """Redirect to Microsoft OAuth consent. ENT-201."""
    if not get_settings().oauth_microsoft_client_id:
        raise HTTPException(status_code=404, detail="Microsoft OAuth not configured")
    state = generate_state()
    redirect_uri = _oauth_redirect_uri("microsoft")
    url = microsoft_authorize_url(redirect_uri, state)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=f"{state}|microsoft",
        **_session_cookie_kwargs(OAUTH_STATE_MAX_AGE),
    )
    return response


@router.get("/oauth/microsoft/callback")
async def oauth_microsoft_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Handle Microsoft OAuth callback; find or create user, issue session. ENT-201."""
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    if not cookie or "|" not in cookie:
        raise HTTPException(status_code=400, detail="Invalid state")
    cookie_state, provider = cookie.strip().split("|", 1)
    if provider != "microsoft" or cookie_state != state:
        try:
            persist_audit(db, "auth.oauth_failed", details={"provider": "microsoft", "reason": "invalid_state"})
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Invalid state")
    ip_key = f"oauth_callback:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    record_attempt(ip_key)
    try:
        return await _oauth_microsoft_callback_impl(request, code, db)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("oauth_microsoft_callback database error: %s", e)
        if _is_db_connection_error(e):
            raise HTTPException(status_code=503, detail="Database unavailable. Please try again later.")
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")
    except Exception as e:
        logger.exception("oauth_microsoft_callback 500: %s", e)
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")


async def _oauth_microsoft_callback_impl(request: Request, code: str, db: Session):
    """Inner Microsoft OAuth callback (wrapped by route for safe 500/503)."""
    redirect_uri = _oauth_redirect_uri("microsoft")
    info = await microsoft_exchange_code(code, redirect_uri)
    if not info or not info.get("provider_user_id"):
        raise HTTPException(status_code=400, detail="Failed to get user info from Microsoft")
    oauth_row = db.query(UserOAuthAccount).filter(
        UserOAuthAccount.provider == "microsoft",
        UserOAuthAccount.provider_user_id == info["provider_user_id"],
    ).first()
    if oauth_row:
        user = db.query(User).filter(User.id == oauth_row.user_id).first()
    else:
        user = None
        if info.get("email") and info.get("email_verified"):
            user = db.query(User).filter(User.email == info.get("email")).first()
            if user:
                db.add(UserOAuthAccount(
                    user_id=user.id,
                    provider="microsoft",
                    provider_user_id=info["provider_user_id"],
                    email=info.get("email"),
                ))
                db.commit()
        elif info.get("email") and not info.get("email_verified"):
            logger.warning("oauth_microsoft_callback email not verified by provider, skipping auto-link")
    if not user:
        email = (info.get("email") or "").strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="Microsoft did not provide an email")
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=info.get("name"),
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        default_workspace_id = 1
        db.add(WorkspaceMember(workspace_id=default_workspace_id, user_id=user.id, role="editor"))
        db.add(UserOAuthAccount(
            user_id=user.id,
            provider="microsoft",
            provider_user_id=info["provider_user_id"],
            email=email,
        ))
        db.commit()
    member = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.workspace_id).first()
    if not member:
        raise HTTPException(status_code=403, detail="No workspace access")
    persist_audit(db, "auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id, details={"provider": "microsoft"})
    resp = _oauth_set_session_and_redirect(user, member.workspace_id, member.role, db)
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/", samesite="lax")
    return resp


# ----- ENT-203: Enterprise OIDC SSO; ENT-204: JIT provisioning -----

SSO_STATE_COOKIE = "sso_state"
SSO_STATE_MAX_AGE = 600


@router.get("/sso")
async def sso_start(request: Request, response: Response):
    """Redirect to configured OIDC IdP. WEB-214 entry point."""
    s = get_settings()
    if not s.oidc_issuer_url or not s.oidc_client_id:
        raise HTTPException(status_code=404, detail="SSO not configured")
    discovery = await oidc_discover(s.oidc_issuer_url)
    if not discovery:
        raise HTTPException(status_code=502, detail="SSO provider discovery failed")
    redirect_uri = _sso_redirect_uri()
    state = generate_state()
    url = oidc_authorize_url(state, redirect_uri, discovery, s.oidc_scope)
    if not url:
        raise HTTPException(status_code=502, detail="SSO configuration error")
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie(
        key=SSO_STATE_COOKIE,
        value=state,
        **_session_cookie_kwargs(SSO_STATE_MAX_AGE),
    )
    return resp


@router.get("/sso/callback")
async def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """OIDC callback: exchange code, JIT user/workspace (ENT-204), issue session."""
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    cookie = request.cookies.get(SSO_STATE_COOKIE)
    if not cookie or cookie.strip() != state:
        try:
            persist_audit(db, "auth.sso_failed", details={"reason": "invalid_state"})
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Invalid state")
    ip_key = f"oauth_callback:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    record_attempt(ip_key)
    try:
        return await _sso_callback_impl(request, code, state, db)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("sso_callback database error: %s", e)
        if _is_db_connection_error(e):
            raise HTTPException(status_code=503, detail="Database unavailable. Please try again later.")
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")
    except Exception as e:
        logger.exception("sso_callback 500: %s", e)
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")


async def _sso_callback_impl(request: Request, code: str, state: str, db: Session):
    """Inner OIDC SSO callback (wrapped by route for safe 500/503)."""
    s = get_settings()
    discovery = await oidc_discover(s.oidc_issuer_url)
    if not discovery:
        raise HTTPException(status_code=502, detail="SSO provider unavailable")
    redirect_uri = _sso_redirect_uri()
    info = await oidc_exchange_code(code, redirect_uri, discovery)
    if not info or not info.get("provider_user_id"):
        raise HTTPException(status_code=400, detail="SSO user info failed")
    provider = "oidc"
    oauth_row = db.query(UserOAuthAccount).filter(
        UserOAuthAccount.provider == provider,
        UserOAuthAccount.provider_user_id == info["provider_user_id"],
    ).first()
    if oauth_row:
        user = db.query(User).filter(User.id == oauth_row.user_id).first()
    else:
        user = None
        if info.get("email") and info.get("email_verified"):
            user = db.query(User).filter(User.email == info.get("email")).first()
            if user:
                db.add(UserOAuthAccount(
                    user_id=user.id,
                    provider=provider,
                    provider_user_id=info["provider_user_id"],
                    email=info.get("email"),
                ))
                db.commit()
        elif info.get("email") and not info.get("email_verified"):
            logger.warning("oauth_oidc_callback email not verified by provider, skipping auto-link")
    if not user:
        email = (info.get("email") or "").strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="SSO did not provide an email")
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=info.get("name"),
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        default_workspace_id = s.oidc_default_workspace_id
        db.add(WorkspaceMember(workspace_id=default_workspace_id, user_id=user.id, role="editor"))
        db.add(UserOAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=info["provider_user_id"],
            email=email,
        ))
        db.commit()
    member = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.workspace_id).first()
    if not member:
        raise HTTPException(status_code=403, detail="No workspace access")
    persist_audit(db, "auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id, details={"provider": "oidc_sso"})
    resp = _oauth_set_session_and_redirect(user, member.workspace_id, member.role, db)
    resp.delete_cookie(SSO_STATE_COOKIE, path="/", samesite="lax")
    return resp


# ----- ENT-205: id.me; ENT-206: hardened callback -----

IDME_STATE_COOKIE = "idme_state"
IDME_STATE_MAX_AGE = 600


@router.get("/idme")
async def idme_start(request: Request, response: Response):
    """Redirect to id.me authorization. ENT-205."""
    if not get_settings().idme_client_id:
        raise HTTPException(status_code=404, detail="id.me not configured")
    redirect_uri = _idme_redirect_uri()
    state = generate_state()
    url = idme_authorize_url(redirect_uri, state)
    if not url:
        raise HTTPException(status_code=502, detail="id.me configuration error")
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie(
        key=IDME_STATE_COOKIE,
        value=state,
        **_session_cookie_kwargs(IDME_STATE_MAX_AGE),
    )
    return resp


@router.get("/idme/callback")
async def idme_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """id.me callback. ENT-206: strict state validation, static redirect URI, server-side token only."""
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    cookie = request.cookies.get(IDME_STATE_COOKIE)
    if not cookie or cookie.strip() != state:
        try:
            persist_audit(db, "auth.idme_failed", details={"reason": "invalid_state"})
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Invalid state")
    ip_key = f"oauth_callback:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    record_attempt(ip_key)
    try:
        return await _idme_callback_impl(request, code, db)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("idme_callback database error: %s", e)
        if _is_db_connection_error(e):
            raise HTTPException(status_code=503, detail="Database unavailable. Please try again later.")
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")
    except Exception as e:
        logger.exception("idme_callback 500: %s", e)
        raise HTTPException(status_code=500, detail="Sign-in could not be completed. Please try again.")


async def _idme_callback_impl(request: Request, code: str, db: Session):
    """Inner id.me callback (wrapped by route for safe 500/503)."""
    redirect_uri = _idme_redirect_uri()
    info = await idme_exchange_code(code, redirect_uri)
    if not info or not info.get("provider_user_id"):
        raise HTTPException(status_code=400, detail="id.me user info failed")
    provider = "idme"
    oauth_row = db.query(UserOAuthAccount).filter(
        UserOAuthAccount.provider == provider,
        UserOAuthAccount.provider_user_id == info["provider_user_id"],
    ).first()
    if oauth_row:
        user = db.query(User).filter(User.id == oauth_row.user_id).first()
    else:
        user = None
        if info.get("email") and info.get("email_verified"):
            user = db.query(User).filter(User.email == info.get("email")).first()
            if user:
                db.add(UserOAuthAccount(
                    user_id=user.id,
                    provider=provider,
                    provider_user_id=info["provider_user_id"],
                    email=info.get("email"),
                ))
                db.commit()
        elif info.get("email") and not info.get("email_verified"):
            logger.warning("oauth_idme_callback email not verified by provider, skipping auto-link")
    if not user:
        email = (info.get("email") or "").strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="id.me did not provide an email")
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=info.get("name"),
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        default_workspace_id = get_settings().oidc_default_workspace_id
        db.add(WorkspaceMember(workspace_id=default_workspace_id, user_id=user.id, role="editor"))
        db.add(UserOAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=info["provider_user_id"],
            email=email,
        ))
        db.commit()
    member = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.workspace_id).first()
    if not member:
        raise HTTPException(status_code=403, detail="No workspace access")
    persist_audit(db, "auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id, details={"provider": "idme"})
    resp = _oauth_set_session_and_redirect(user, member.workspace_id, member.role, db)
    resp.delete_cookie(IDME_STATE_COOKIE, path="/", samesite="lax")
    return resp


# Suspicious actions we surface as alerts (WEB-211)
SUSPICIOUS_ACTIONS = frozenset({
    "auth.mfa_verify_failed",
    "auth.mfa_confirm_failed",
    "auth.mfa_disable_failed",
    "auth.login_failed",  # when user_id present, e.g. no_workspace
})


@router.get("/alerts")
async def list_alerts(session: dict = Depends(require_valid_session), db: Session = Depends(get_db)):
    """WEB-211: Recent suspicious auth events for current user (in-app alerts)."""
    user_id = session.get("user_id")
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.user_id == user_id,
            AuditEvent.action.in_(SUSPICIOUS_ACTIONS),
            AuditEvent.occurred_at >= since,
        )
        .order_by(AuditEvent.occurred_at.desc())
        .limit(10)
        .all()
    )
    return {
        "alerts": [
            {
                "id": r.id,
                "action": r.action,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "details": r.details,
            }
            for r in rows
        ],
    }


def _permissions(role: str | None, workspace_id: int | None = None, db=None) -> dict:
    if roles.is_builtin_role(role):
        return {
            "can_edit": roles.can_edit(role),
            "can_review": roles.can_review(role),
            "can_admin": roles.can_admin(role),
            "can_export": roles.can_export(role),
        }
    if db and workspace_id and role:
        from app.models import CustomRole
        cr = db.query(CustomRole).filter(CustomRole.workspace_id == workspace_id, CustomRole.name == role).first()
        if cr:
            return {
                "can_edit": bool(cr.can_edit),
                "can_review": bool(cr.can_review),
                "can_admin": bool(cr.can_admin),
                "can_export": bool(cr.can_export),
            }
    return {"can_edit": False, "can_review": False, "can_admin": False, "can_export": False}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    """Return current user, workspace, workspaces list, role, permissions (AUTH-203)."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = verify_token(cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    session_id = session.get("session_id")
    if session_id:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        if not row:
            raise HTTPException(status_code=401, detail="Session invalidated")
    user_id = session.get("user_id")
    workspace_id = session.get("workspace_id", 1)
    role = session.get("role", "editor")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if workspace_id == 0 or role == "pending":
        return {
            "id": user.id,
            "email": user.email or "",
            "display_name": getattr(user, "display_name", None) or "User",
            "workspace_id": 0,
            "workspace_name": "",
            "workspace_slug": "",
            "role": "pending",
            "workspaces": [],
            "permissions": {"can_edit": False, "can_review": False, "can_admin": False, "can_export": False},
            "needs_onboarding": True,
            "mfa_enrolled": False,
            "mfa_required_for_workspace": False,
            "workspace_auth_policy": {"mfa_required": False, "session_max_age_seconds": None},
        }
    current_ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    memberships = (
        db.query(WorkspaceMember, Workspace)
        .join(Workspace, WorkspaceMember.workspace_id == Workspace.id)
        .filter(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.id)
        .all()
    )
    workspaces = [
        {"id": ws.id, "name": getattr(ws, "name", "Workspace"), "slug": getattr(ws, "slug", ""), "role": mem.role}
        for mem, ws in memberships
    ]
    from app.models import Subscription
    active_sub = db.query(Subscription).filter(
        Subscription.workspace_id == workspace_id,
        Subscription.status.in_(["active", "trialing"]),
    ).first()

    mfa_row = db.query(UserMfa).filter(UserMfa.user_id == user_id, UserMfa.enabled.is_(True)).first()
    user_has_mfa = bool(mfa_row)
    ws_mfa_required = bool(current_ws and getattr(current_ws, "mfa_required", False))
    return {
        "id": user.id,
        "email": user.email or "",
        "display_name": getattr(user, "display_name", None) or "User",
        "workspace_id": workspace_id,
        "workspace_name": getattr(current_ws, "name", "Default") if current_ws else "Default",
        "workspace_slug": getattr(current_ws, "slug", "") if current_ws else "",
        "role": role,
        "workspaces": workspaces,
        "permissions": _permissions(role, workspace_id, db),
        "mfa_enrolled": user_has_mfa,
        "mfa_required_for_workspace": ws_mfa_required and not user_has_mfa,
        "workspace_auth_policy": {
            "mfa_required": ws_mfa_required,
            "session_max_age_seconds": getattr(current_ws, "session_max_age_seconds", None) if current_ws else None,
        },
        "subscription": {
            "status": active_sub.status if active_sub else "none",
            "plan": active_sub.plan if active_sub else None,
        },
    }


@router.post("/switch-workspace", response_model=dict)
async def switch_workspace(
    body: SwitchWorkspaceRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Switch active workspace; reissue session with new workspace_id and role (AUTH-204)."""
    session = await require_session(request, db)
    user_id = session.get("user_id")
    email = session.get("email", "")
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == body.workspace_id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    ws = db.query(Workspace).filter(Workspace.id == body.workspace_id).first()
    existing_session_id = session.get("session_id")
    if not existing_session_id:
        raise HTTPException(status_code=400, detail="Cannot switch workspace for legacy session")
    max_age = _session_max_age_seconds(db, member.workspace_id)
    token = sign_session(
        user_id=user_id,
        email=email,
        workspace_id=member.workspace_id,
        role=member.role,
        session_id=existing_session_id,
        max_age_seconds=max_age,
    )
    response.set_cookie(key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age))
    persist_audit(
        db,
        "auth.workspace_switch",
        user_id=user_id,
        email=email,
        workspace_id=member.workspace_id,
        details={"workspace_name": ws.name if ws else "Default", "role": member.role},
    )
    return {
        "workspace_id": member.workspace_id,
        "workspace_name": ws.name if ws else "Default",
        "workspace_slug": getattr(ws, "slug", "") if ws else "",
        "role": member.role,
    }


# ----- AUTH-208: Accept invite (public endpoint) -----


@router.post("/verify-invite-code")
def verify_invite_code(req: VerifyInviteCodeRequest, request: Request, db: Session = Depends(get_db)):
    """Exchange email + verification code from the invite email for a one-time token used by POST /accept-invite."""
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email or verification code")
    client_ip = get_client_ip(request)
    rl_key = f"invite_verify:{client_ip}:{email}"
    if is_rate_limited(rl_key, max_attempts=10, window_sec=900):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    code_input = (req.code or "").strip()
    if not code_input:
        record_attempt(rl_key, max_attempts=10, window_sec=900)
        raise HTTPException(status_code=400, detail="Invalid email or verification code")
    ch = hash_invite_code(code_input)
    invites = db.query(Invite).filter(Invite.email == email).all()
    now = datetime.now(timezone.utc)
    matched: Invite | None = None
    for inv in invites:
        if not inv.invite_code_hash:
            continue
        exp = inv.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            continue
        if secrets.compare_digest(inv.invite_code_hash, ch):
            matched = inv
            break
    if not matched:
        record_attempt(rl_key, max_attempts=10, window_sec=900)
        raise HTTPException(status_code=400, detail="Invalid email or verification code")
    new_token = secrets.token_urlsafe(32)
    matched.token_hash = _token_hash(new_token)
    db.commit()
    return {"token": new_token}


@router.post("/accept-invite")
def accept_invite(req: AcceptInviteRequest, db: Session = Depends(get_db)):
    """AUTH-208: Accept workspace invite by token. New user: set password and create account. Existing user: confirm email and add to workspace.
    For new invites, obtain token via POST /verify-invite-code. Legacy invites (no verification code) may still use a token from an old link."""
    if not req.token or not req.token.strip():
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    h = _token_hash(req.token.strip())
    inv = db.query(Invite).filter(Invite.token_hash == h).first()
    if not inv:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    now = datetime.now(timezone.utc)
    exp = inv.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        db.delete(inv)
        db.commit()
        raise HTTPException(status_code=400, detail="Link expired")
    email = (inv.email or "").strip().lower()
    if not email or "@" not in email:
        db.delete(inv)
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid invite")
    user = db.query(User).filter(User.email == email).first()
    if user:
        existing_mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == inv.workspace_id,
            WorkspaceMember.user_id == user.id,
        ).first()
        if existing_mem:
            db.delete(inv)
            db.commit()
            raise HTTPException(status_code=400, detail="You are already a member of this workspace")
        user.email_verified = True
        mem = WorkspaceMember(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role)
        db.add(mem)
        db.delete(inv)
        db.commit()
        persist_audit(db, "auth.invite_accepted", user_id=user.id, email=email, workspace_id=inv.workspace_id, details={"role": inv.role})
        return {"message": "You have joined the workspace. You can sign in."}
    if not req.password or len(req.password.strip()) < 6:
        raise HTTPException(status_code=400, detail="Set a password to create your account (at least 6 characters)")
    user = User(
        email=email,
        password_hash=hash_password(req.password.strip()),
        display_name=None,
        email_verified=True,
    )
    db.add(user)
    db.flush()
    mem = WorkspaceMember(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role)
    db.add(mem)
    db.delete(inv)
    db.commit()
    persist_audit(db, "auth.invite_accepted_new_user", user_id=user.id, email=email, workspace_id=inv.workspace_id, details={"role": inv.role})
    return {"message": "Account created. You can sign in."}


# ----- AUTH-211: MFA (TOTP, login challenge) -----


def _recovery_code_hash(code: str) -> str:
    """Normalize and hash recovery code for lookup."""
    normalized = (code or "").strip().upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalized.encode()).hexdigest()


@router.get("/mfa/status")
async def mfa_status(request: Request, db: Session = Depends(get_db)):
    """Return whether current user has MFA enabled."""
    session = await require_session(request, db)
    user_id = session.get("user_id")
    row = db.query(UserMfa).filter(UserMfa.user_id == user_id).first()
    return {"enabled": bool(row and row.enabled)}


@router.post("/mfa/setup")
async def mfa_setup(request: Request, db: Session = Depends(get_db)):
    """Start MFA enrollment: generate secret, return provisioning_uri for QR. Does not enable until confirm."""
    session = await require_session(request, db)
    user_id = session.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    existing = db.query(UserMfa).filter(UserMfa.user_id == user_id).first()
    if existing and existing.enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(secret)
    if existing:
        existing.totp_secret_encrypted = encrypted
        existing.enabled = False
        db.commit()
    else:
        um = UserMfa(user_id=user_id, totp_secret_encrypted=encrypted, enabled=False)
        db.add(um)
        db.commit()
    provisioning_uri = get_totp_uri(secret, user.email or "user")
    persist_audit(db, "auth.mfa_setup_started", user_id=user_id, email=user.email)
    return {"secret": secret, "provisioning_uri": provisioning_uri}


@router.post("/mfa/confirm")
async def mfa_confirm(req: MfaConfirmRequest, request: Request, db: Session = Depends(get_db)):
    """Verify TOTP code and enable MFA; generate and return recovery codes (one-time display)."""
    session = await require_session(request, db)
    user_id = session.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    row = db.query(UserMfa).filter(UserMfa.user_id == user_id).first()
    if not row:
        raise HTTPException(status_code=400, detail="Start MFA setup first")
    if row.enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    secret = decrypt_totp_secret(row.totp_secret_encrypted)
    if not verify_totp(secret, (req.code or "").strip()):
        persist_audit(db, "auth.mfa_confirm_failed", user_id=user_id, email=user.email)
        raise HTTPException(status_code=400, detail="Invalid code")
    row.enabled = True
    recovery_codes_raw = []
    for _ in range(10):
        code = secrets.token_hex(4).upper()
        code = f"{code[:4]}-{code[4:]}"  # XXXXX-XXXX format
        recovery_codes_raw.append(code)
        db.add(MfaRecoveryCode(user_id=user_id, code_hash=_recovery_code_hash(code)))
    db.commit()
    persist_audit(db, "auth.mfa_enabled", user_id=user_id, email=user.email)
    return {"recovery_codes": recovery_codes_raw}


@router.post("/mfa/verify-login")
def mfa_verify_login(req: MfaVerifyLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Complete login after MFA: accept mfa_token + code (TOTP or recovery), issue session (AUTH-211)."""
    code = (req.code or "").strip()
    token_raw = (req.mfa_token or "").strip()
    if not token_raw or not code:
        raise HTTPException(status_code=400, detail="Missing mfa_token or code")
    client_ip = get_client_ip(request)
    ip_key = f"mfa:ip:{client_ip}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    record_attempt(ip_key)
    h = _token_hash(token_raw)
    mlt = db.query(MfaLoginToken).filter(MfaLoginToken.token_hash == h).first()
    if not mlt:
        raise HTTPException(status_code=400, detail="Invalid or expired MFA token")
    now = datetime.now(timezone.utc)
    exp = mlt.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        db.delete(mlt)
        db.commit()
        raise HTTPException(status_code=400, detail="MFA token expired")
    user = db.query(User).filter(User.id == mlt.user_id).first()
    if not user:
        db.delete(mlt)
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid token")
    mfa_row = db.query(UserMfa).filter(UserMfa.user_id == user.id, UserMfa.enabled.is_(True)).first()
    if not mfa_row:
        db.delete(mlt)
        db.commit()
        raise HTTPException(status_code=400, detail="MFA not enabled")
    verified = False
    if len(code) == 6 and code.isdigit():
        secret = decrypt_totp_secret(mfa_row.totp_secret_encrypted)
        verified = verify_totp(secret, code)
    if not verified:
        code_hash = _recovery_code_hash(code)
        rc = db.query(MfaRecoveryCode).filter(
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.code_hash == code_hash,
            MfaRecoveryCode.used_at.is_(None),
        ).first()
        if rc:
            rc.used_at = now
            verified = True
            persist_audit(db, "auth.mfa_recovery_used", user_id=user.id, email=user.email)
    if not verified:
        persist_audit(db, "auth.mfa_verify_failed", user_id=user.id, email=user.email)
        send_suspicious_login_email(user.email, "Failed two-factor verification")
        raise HTTPException(status_code=400, detail="Invalid code")
    db.delete(mlt)
    session_id = secrets.token_urlsafe(32)
    db.add(UserSession(
        user_id=user.id,
        session_id=session_id,
        user_agent=request.headers.get("user-agent"),
        ip_address=get_client_ip(request),
    ))
    db.commit()
    audit_log("auth.login", user_id=user.id, email=user.email, workspace_id=mlt.workspace_id)
    persist_audit(db, "auth.login", user_id=user.id, email=user.email, workspace_id=mlt.workspace_id)
    remember = bool(req.remember_me)
    max_age = _effective_session_max_age_seconds(db, mlt.workspace_id, remember)
    token = sign_session(
        user_id=user.id,
        email=user.email,
        workspace_id=mlt.workspace_id,
        role=mlt.role,
        session_id=session_id,
        max_age_seconds=max_age,
    )
    response.set_cookie(key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age, persistent=remember))
    return {"user": _user_response(user), "workspace_id": mlt.workspace_id}


@router.post("/mfa/disable")
async def mfa_disable(req: MfaDisableRequest, request: Request, db: Session = Depends(get_db)):
    """Disable MFA for current user. Requires password for confirmation."""
    session = await require_session(request, db)
    user_id = session.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not verify_password((req.password or "").strip(), user.password_hash):
        persist_audit(db, "auth.mfa_disable_failed", user_id=user_id, email=user.email)
        raise HTTPException(status_code=400, detail="Invalid password")
    db.query(UserMfa).filter(UserMfa.user_id == user_id).delete()
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user_id).delete()
    db.commit()
    persist_audit(db, "auth.mfa_disabled", user_id=user_id, email=user.email)
    return {"ok": True}
