"""Auth API (AUTH-02, AUTH-03, AUTH-201, AUTH-203, AUTH-204, AUTH-207)."""

import os
import base64
import hashlib
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response

logger = logging.getLogger(__name__)
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy.exc import OperationalError, SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.api_errors import ApiError, api_error_response, current_request_id  # noqa: E402
from app.core.audit import audit_log, persist_audit, record_decrypt_failure  # noqa: E402
from app.core.debug_session_log import append_session_debug  # noqa: E402
from app.core.auth_deps import (  # noqa: E402
    DEFAULT_SESSION_MAX_AGE_SECONDS,
    enforce_mfa_enrol_session,
    enforce_session_record,
    get_session,
    require_session,
    require_session_leaving_workspace,
    require_valid_session,
    resolve_current_membership,
    workspace_requires_unmet_mfa,
    workspace_session_max_age_seconds,
)
from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal, get_db  # noqa: E402
from app.core.keys import KeyErrorSafe, MfaReenrolRequired  # noqa: E402
from app.core.mfa import (  # noqa: E402
    decrypt_mfa_for_user,
    encrypt_totp_secret,
    generate_totp_secret,
    get_totp_uri,
    mfa_reenrol_required,
    mfa_reenrol_pending,
    verify_totp,
)
from app.core.password import hash_password, verify_password  # noqa: E402
from app.core.rate_limit import (  # noqa: E402
    RateLimitBackendError,
    get_client_ip,
    is_rate_limited,
    record_attempt,
)
from app.core.keys import purpose_macs  # noqa: E402
from app.core.session import (  # noqa: E402
    is_production_env,
    sign_session,
    verify_token,
)
from app.models import (  # noqa: E402
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
from app.core import roles  # noqa: E402
from app.core.invite_codes import hash_invite_code  # noqa: E402
from app.services.email_service import (  # noqa: E402
    send_password_reset_email,
    send_suspicious_login_email,
    send_verification_code_email,
    send_verification_email,  # noqa: F401
)
from app.services.oauth_service import (  # noqa: E402
    generate_state,
    google_authorize_url,
    google_exchange_code,
    github_authorize_url,
    github_exchange_code,
    microsoft_authorize_url,
    microsoft_exchange_code,
)
from app.services.sso_service import (  # noqa: E402
    idme_authorize_url,
    idme_exchange_code,
    oidc_authorize_url,
    oidc_discover,
    oidc_exchange_code,
)

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "tc_session"
SESSION_MAX_AGE = DEFAULT_SESSION_MAX_AGE_SECONDS


def _session_cookie_kwargs(max_age: int, persistent: bool = True) -> dict:
    """Secure cookie kwargs: HttpOnly, SameSite=lax, path=/.

    When persistent=True (remember me), max_age is set so the cookie
    survives browser restarts.  When persistent=False, max_age is omitted
    so the browser treats it as a session cookie deleted on close.
    The JWT token inside still has an exp claim for server-side validation.
    """
    kw: dict = {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": is_production_env(),
    }
    if persistent:
        kw["max_age"] = max_age
    return kw


def _session_max_age_seconds(db: Session, workspace_id: int) -> int:
    """ENT-202: Per-workspace session lifetime, or default."""
    return workspace_session_max_age_seconds(db, workspace_id)


def _effective_session_max_age_seconds(db: Session, workspace_id: int, remember_me: bool) -> int:
    """Remember-me changes cookie persistence, never the tenant's lifetime cap."""
    return _session_max_age_seconds(db, workspace_id)


def _member_workspace_requires_mfa(db: Session, workspace_id: int) -> bool:
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    return bool(workspace and workspace.mfa_required)


def _store_mfa_login_token(db: Session, user: User, member: WorkspaceMember) -> str:
    """Pending MFA login. No session row and no privileged cookie."""
    raw = secrets.token_urlsafe(32)
    db.add(
        MfaLoginToken(
            token_hash=_token_hash(raw),
            user_id=user.id,
            workspace_id=member.workspace_id,
            role=member.role,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )
    db.commit()
    return raw


def _enabled_mfa_factor(factor: UserMfa | None) -> bool:
    """True when this factor can complete a login challenge.

    A disabled setup, an administrator re-enrolment, and an undecryptable
    reset marker are not an enabled factor.
    """
    if factor is None or not factor.enabled:
        return False
    stored = factor.totp_secret_encrypted
    if mfa_reenrol_required(stored) or mfa_reenrol_pending(stored):
        return False
    return True


def _session_mfa_satisfied(db: Session, user_id: int, session_id: str | None) -> bool:
    """True only when this stored session was created after a completed challenge.

    A missing row or a false flag is not satisfied. Sessions from before the
    column existed are false and must challenge again.
    """
    if type(user_id) is not int or not isinstance(session_id, str) or not session_id.strip():
        return False
    try:
        row = (
            db.query(UserSession)
            .filter(UserSession.session_id == session_id, UserSession.user_id == user_id)
            .populate_existing()
            .first()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Session policy unavailable") from exc
    return bool(row and row.mfa_satisfied)


def _mfa_required_for_workspace_flag(workspace: Workspace | None, factor: UserMfa | None) -> bool:
    """Same flag GET /api/auth/me reports for a normal session."""
    required = bool(workspace and workspace.mfa_required)
    enrolled = bool(factor and factor.enabled)
    return required and not enrolled


def _mfa_challenge_response(
    db: Session,
    user: User,
    member: WorkspaceMember,
    *,
    details: dict | None = None,
) -> dict:
    """The password-login challenge: no session cookie, five-minute token."""
    raw = _store_mfa_login_token(db, user, member)
    persist_audit(
        db,
        "auth.mfa_required",
        user_id=user.id,
        email=user.email,
        workspace_id=member.workspace_id,
        details=details,
    )
    return {"requires_mfa": True, "mfa_token": raw}


def _frontend_login_url(query: dict[str, str] | None = None) -> str:
    base = get_settings().frontend_url.rstrip("/")
    if not query:
        return f"{base}/login"
    return f"{base}/login?{urlencode(query)}"


def _clear_provider_state(resp: RedirectResponse, state_cookie: str) -> RedirectResponse:
    resp.delete_cookie(state_cookie, path="/", samesite="lax")
    return resp


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
    invalidate_other_sessions: bool = Field(
        default=False,
        description=(
            "Accepted for compatibility and ignored. A successful change always "
            "revokes every other session and keeps the current one."
        ),
    )


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


# Five attempts are allowed. The stored counter is incremented before the check,
# so the limiter trips when the count reaches six and a parallel burst cannot pass five.
_VERIFY_MAX_ATTEMPTS = 5
_VERIFY_RECORDED_LIMIT = _VERIFY_MAX_ATTEMPTS + 1
_VERIFY_LOCKOUT_SECONDS = 900
_LINK_TOKEN_MIN_LENGTH = 32
_RESEND_MAX_ATTEMPTS = 3
_RESEND_RECORDED_LIMIT = _RESEND_MAX_ATTEMPTS + 1
_RESEND_WINDOW_SECONDS = 900
_CODE_MAC_LABEL = "email-verification-code:"


def _is_six_digit_code(value: str) -> bool:
    return len(value) == 6 and value.isdigit()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _verification_code_key(code: str) -> str:
    """Rate-limit key for one submitted code. This is not the stored digest."""
    return f"verify-code:submitted:{_token_hash(code)}"


def _verification_user_key(user_id: int) -> str:
    return f"verify-code:user:{user_id}"


def _verification_email_key(email: str) -> str:
    return f"verify-code:email:{email}"


def _code_macs(code: str) -> tuple[str, ...]:
    """HMAC of a 6-digit code under the session purpose key. The code is not stored."""
    return purpose_macs("session", f"{_CODE_MAC_LABEL}{code}")


def _rate_limited(*keys: str, max_attempts: int, window_sec: float) -> bool:
    try:
        return any(
            is_rate_limited(
                key,
                max_attempts=max_attempts,
                window_sec=window_sec,
                fail_closed=is_production_env(),
            )
            for key in keys
        )
    except RateLimitBackendError:
        raise HTTPException(
            status_code=503,
            detail="Verification is temporarily unavailable. Try again later.",
        )


def _verification_attempt(*keys: str) -> None:
    """Record the attempt, then refuse once the cap is exceeded."""
    for key in keys:
        record_attempt(key, max_attempts=_VERIFY_RECORDED_LIMIT, window_sec=_VERIFY_LOCKOUT_SECONDS)
    if _rate_limited(
        *keys, max_attempts=_VERIFY_RECORDED_LIMIT, window_sec=_VERIFY_LOCKOUT_SECONDS
    ):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")


def _delete_verification_tokens(db: Session, user_id: int) -> None:
    db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user_id).delete(
        synchronize_session=False
    )


def _delete_user_sessions(db: Session, user_id: int) -> None:
    db.query(UserSession).filter(UserSession.user_id == user_id).delete(synchronize_session=False)


def _mark_email_verified(db: Session, user: User) -> None:
    user.email_verified = True
    _delete_verification_tokens(db, user.id)
    _delete_user_sessions(db, user.id)
    db.commit()
    persist_audit(db, "auth.email_verified", user_id=user.id, email=user.email)


def _issue_verification(_db: Session, user: User, email: str) -> None:
    """Queue a code and link. The request does not wait for the provider.

    A background session inserts the rows and commits them only after the
    provider accepts. A false or raised send rolls those rows back, so a code
    or link that was already delivered stays usable.
    """
    code = f"{secrets.randbelow(10**6):06d}"
    link = secrets.token_urlsafe(32)
    _spawn_identity_mail(_deliver_verification, (user.id, email, code, link))


@router.post("/register")
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Register; create user (email_verified=False), send verification code + link.

    A second registration for the same address does not change the password,
    the verification state, or workspace membership.
    """
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    password = (req.password or "").strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password too short")
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return {
            "message": "If that email is not yet registered, you will receive a verification code."
        }
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=(req.display_name or "").strip() or None,
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _issue_verification(db, user, email)
    persist_audit(db, "auth.register", user_id=user.id, email=email)
    return {"message": "If that email is not yet registered, you will receive a verification code."}


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


@router.post("/verify-code")
def verify_code(req: VerifyCodeRequest, db: Session = Depends(get_db)):
    """Verify email using the 6-digit code mailed to that address.

    The code is matched only for that user. Failed attempts are counted per
    address, per account, and per submitted code, then locked out.
    """
    email = (req.email or "").strip().lower()
    code = (req.code or "").strip()
    if not email or not code:
        raise HTTPException(status_code=400, detail="Email and code are required")
    user = db.query(User).filter(User.email == email).first()
    keys = [_verification_email_key(email)]
    if user is not None:
        keys.append(_verification_user_key(user.id))
    if _is_six_digit_code(code):
        keys.append(_verification_code_key(code))
    _verification_attempt(*keys)
    if not _is_six_digit_code(code):
        raise HTTPException(status_code=400, detail="Invalid code")
    if user is not None:
        user = _for_update(db, db.query(User).filter(User.id == user.id)).first()
    evt = None
    if user is not None:
        evt = _for_update(
            db,
            db.query(EmailVerificationToken)
            .filter(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.token_hash.in_(_code_macs(code)),
            )
            .populate_existing(),
        ).first()
    if user is None or evt is None:
        raise HTTPException(status_code=400, detail="Invalid code")
    if _as_utc(evt.expires_at) < datetime.now(timezone.utc):
        db.delete(evt)
        db.commit()
        raise HTTPException(status_code=400, detail="Code expired. Please register again.")
    _mark_email_verified(db, user)
    return {"message": "Email verified."}


@router.post("/verify-email")
def verify_email(token: str = "", user: str = "", db: Session = Depends(get_db)):
    """Verify the high-entropy link for one user.

    The 6-digit code is rejected here. Lookup is (user, token), never the
    token alone, and failed attempts lock that account and that token.
    """
    raw = (token or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    try:
        user_id = int(str(user).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    if user_id < 1:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    user_key = f"verify-email:user:{user_id}"
    token_key = f"verify-email:token:{_token_hash(raw)}"
    _verification_attempt(user_key, token_key)
    if len(raw) < _LINK_TOKEN_MIN_LENGTH or _is_six_digit_code(raw):
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    account = db.query(User).filter(User.id == user_id).first()
    if account is not None:
        account = _for_update(db, db.query(User).filter(User.id == account.id)).first()
    evt = None
    if account is not None:
        evt = _for_update(
            db,
            db.query(EmailVerificationToken)
            .filter(
                EmailVerificationToken.user_id == account.id,
                EmailVerificationToken.token_hash == _token_hash(raw),
            )
            .populate_existing(),
        ).first()
    if account is None or evt is None:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    if _as_utc(evt.expires_at) < datetime.now(timezone.utc):
        db.delete(evt)
        db.commit()
        raise HTTPException(status_code=400, detail="Link expired")
    _after_row_locked("verify-email")
    _mark_email_verified(db, account)
    return {"message": "Email verified. You can sign in."}


class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/resend-verification")
def resend_verification(
    req: ResendVerificationRequest, request: Request, db: Session = Depends(get_db)
):
    """Send a fresh code and link for an unverified account. The response is generic."""
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    ip_key = f"resend-verify:ip:{get_client_ip(request)}"
    email_key = f"resend-verify:email:{email}"
    for key in (ip_key, email_key):
        record_attempt(key, max_attempts=_RESEND_RECORDED_LIMIT, window_sec=_RESEND_WINDOW_SECONDS)
    if _rate_limited(
        ip_key, email_key, max_attempts=_RESEND_RECORDED_LIMIT, window_sec=_RESEND_WINDOW_SECONDS
    ):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    user = db.query(User).filter(User.email == email).first()
    if user is not None and not user.email_verified:
        # Do not delete the delivered code here. The background send removes
        # older rows only after the provider accepts the new message.
        _issue_verification(db, user, email)
    return {"message": "If that email is waiting for verification, a new message is on the way."}


_RESET_GENERIC = "If that email is registered, you will receive a reset link."


def _generic_reset_message() -> dict:
    return {"message": _RESET_GENERIC}


def _dev_reset_url_enabled() -> bool:
    """The raw link is a dev aid. Production never returns it, and a failed send does not."""
    if is_production_env():
        return False
    flag = os.environ.get("TRUST_COPILOT_DEV_RETURN_RESET_URL", "").strip().lower()
    return flag in ("1", "true", "yes")


_identity_mail_threads: list[threading.Thread] = []
_identity_mail_guard = threading.Lock()
_skip_identity_mail_drain = False


def skip_identity_mail_drain() -> bool:
    """Tests set this so a timed request is not held open until the provider returns."""
    return _skip_identity_mail_drain


def _spawn_identity_mail(target, args: tuple) -> None:
    """Run issuance off the request thread, on its own database session."""
    thread = threading.Thread(target=target, args=args, daemon=True)
    with _identity_mail_guard:
        _identity_mail_threads.append(thread)
    thread.start()


def drain_identity_mail(timeout: float = 30) -> None:
    """Join issuance threads. The HTTP handlers do not call this."""
    with _identity_mail_guard:
        threads = list(_identity_mail_threads)
    for thread in threads:
        thread.join(timeout=timeout)
    with _identity_mail_guard:
        _identity_mail_threads[:] = [item for item in _identity_mail_threads if item.is_alive()]


def _after_row_locked(_kind: str) -> None:
    """Called after a redemption lock is held. Tests replace this to overlap two submits."""
    return None


def _for_update(db: Session, query):
    """``SELECT ... FOR UPDATE`` on PostgreSQL. SQLite compiles the clause away."""
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        return query.with_for_update()
    return query


def _rollback_unsent(db: Session, model, token_id: int | None, label: str) -> None:
    """Drop an uncommitted issuance. Delete that id if a commit already landed it."""
    try:
        db.rollback()
    except Exception:
        logger.warning("%s issuance rollback failed for token_id=%s", label, token_id)
    if token_id is None:
        return
    try:
        db.query(model).filter(model.id == token_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        logger.warning("Could not delete unsent %s id=%s", label, token_id)
        try:
            db.rollback()
        except Exception:
            logger.warning("Rollback after an unsent %s delete failed for id=%s", label, token_id)


def _audit_reset(
    db: Session,
    action: str,
    user_id: int,
    email: str,
    details: dict | None = None,
) -> None:
    """Record a reset audit without changing the HTTP response when the write fails."""
    try:
        persist_audit(db, action, user_id=user_id, email=email, details=details)
    except Exception:
        logger.warning("Password reset audit %s failed for user_id=%s", action, user_id)


def _deliver_password_reset(user_id: int, email: str, token_raw: str) -> None:
    """Insert, send, then commit or delete. Runs on a session the request does not hold."""
    db = SessionLocal()
    token_id: int | None = None
    try:
        prt = PasswordResetToken(
            user_id=user_id,
            token_hash=_token_hash(token_raw),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(prt)
        db.flush()
        if isinstance(prt.id, int) and not isinstance(prt.id, bool):
            token_id = prt.id
        if token_id is None:
            raise RuntimeError("reset token id was not assigned")
        reset_url = f"{get_settings().frontend_url.rstrip('/')}/reset-password?token={token_raw}"
        sent = False
        reason = "provider_rejected"
        try:
            sent = bool(send_password_reset_email(email, reset_url))
        except Exception as exc:
            sent = False
            reason = "provider_error"
            logger.warning(
                "Password reset email send failed for %s (user_id=%s, %s)",
                email,
                user_id,
                type(exc).__name__,
            )
        if not sent:
            if reason == "provider_rejected":
                logger.warning(
                    "Password reset email was not accepted for delivery to %s (user_id=%s)",
                    email,
                    user_id,
                )
            _rollback_unsent(db, PasswordResetToken, token_id, "password reset")
            _audit_reset(db, "auth.reset_send_failed", user_id, email, {"reason": reason})
            return
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.id < token_id,
        ).delete(synchronize_session=False)
        persist_audit(db, "auth.reset_requested", user_id=user_id, email=email)
    except Exception:
        logger.warning("Password reset issuance failed for user_id=%s", user_id)
        _rollback_unsent(db, PasswordResetToken, token_id, "password reset")
        _audit_reset(db, "auth.reset_send_failed", user_id, email, {"reason": "store_failed"})
    finally:
        db.close()


def _deliver_verification(user_id: int, email: str, code: str, link: str) -> None:
    """Insert a code and link, send, then commit or delete. Own session."""
    db = SessionLocal()
    token_ids: list[int] = []
    try:
        now = datetime.now(timezone.utc)
        code_row = EmailVerificationToken(
            user_id=user_id,
            token_hash=_code_macs(code)[0],
            expires_at=now + timedelta(minutes=15),
        )
        link_row = EmailVerificationToken(
            user_id=user_id,
            token_hash=_token_hash(link),
            expires_at=now + timedelta(hours=24),
        )
        db.add(code_row)
        db.add(link_row)
        db.flush()
        for row in (code_row, link_row):
            if isinstance(row.id, int) and not isinstance(row.id, bool):
                token_ids.append(row.id)
        if len(token_ids) != 2:
            raise RuntimeError("verification token id was not assigned")
        verify_url = (
            f"{get_settings().frontend_url.rstrip('/')}/verify-email?token={link}&user={user_id}"
        )
        sent = False
        reason = "provider_rejected"
        try:
            sent = bool(send_verification_code_email(email, code, verify_url=verify_url))
        except Exception as exc:
            sent = False
            reason = "provider_error"
            logger.warning(
                "Verification email send failed for user_id=%s (%s)",
                user_id,
                type(exc).__name__,
            )
        if not sent:
            if reason == "provider_rejected":
                logger.warning("Verification email was not accepted for user_id=%s", user_id)
            db.rollback()
            for token_id in token_ids:
                _rollback_unsent(db, EmailVerificationToken, token_id, "verification")
            _audit_reset(db, "auth.verification_send_failed", user_id, email, {"reason": reason})
            return
        oldest = min(token_ids)
        db.query(EmailVerificationToken).filter(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.id < oldest,
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        logger.warning("Verification issuance failed for user_id=%s", user_id)
        try:
            db.rollback()
        except Exception:
            logger.warning("Verification issuance rollback failed for user_id=%s", user_id)
        for token_id in token_ids:
            _rollback_unsent(db, EmailVerificationToken, token_id, "verification")
        _audit_reset(
            db, "auth.verification_send_failed", user_id, email, {"reason": "store_failed"}
        )
    finally:
        db.close()


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Request a password reset. The response does not say whether the address exists.

    Every address returns before the provider is called, so a known address is
    not slower than an unknown one. A background session then inserts the new
    row, sends, and commits it only if the provider accepts. A false or raised
    send deletes that row and leaves a previously delivered link in place.
    Older unused rows are deleted only after acceptance, and only when their id
    is lower than the new row. The failure is logged without the reset URL and
    stored as ``auth.reset_send_failed``.
    """
    email = (req.email or "").strip().lower()
    ip_key = f"reset:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return _generic_reset_message()
    record_attempt(ip_key)
    token_raw = secrets.token_urlsafe(32)
    _spawn_identity_mail(_deliver_password_reset, (user.id, email, token_raw))
    msg = _generic_reset_message()
    if _dev_reset_url_enabled():
        # Candidate link. The row is stored only after the provider accepts.
        msg["reset_url"] = (
            f"{get_settings().frontend_url.rstrip('/')}/reset-password?token={token_raw}"
        )
    return msg


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Set a new password from one token. Do not auto-sign in. Rate limited by IP.

    The account row is locked first, then the unused token row (``SELECT ... FOR
    UPDATE``). A second submit of that same token waits, re-reads, and finds no
    row. SQLite compiles the lock clause away; PostgreSQL holds it until commit.
    """
    ip_key = f"reset_password:ip:{get_client_ip(request)}"
    if is_rate_limited(ip_key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if not req.token or len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Invalid request")
    record_attempt(ip_key)
    h = _token_hash(req.token)
    preview = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == h, PasswordResetToken.used_at.is_(None))
        .first()
    )
    if not preview:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    # Lock the account before the token. Two different links that each locked a
    # token and then deleted every unused row could deadlock. One account lock
    # is the order for every reset of this user.
    user = db.query(User).filter(User.id == preview.user_id).with_for_update().first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    prt = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == h, PasswordResetToken.used_at.is_(None))
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not prt:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    now = datetime.now(timezone.utc)
    exp = prt.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        raise HTTPException(status_code=400, detail="Link expired")
    user.password_hash = hash_password(req.new_password)
    # Retire every unused reset link for this user, including the one just
    # presented. Email-verification rows and MFA recovery codes stay: they are
    # not password-reset credentials. This route does not sign the caller in,
    # so every stored session is removed and there is no current session to keep.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).delete(synchronize_session=False)
    _delete_user_sessions(db, user.id)
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
    """Change the signed-in user's password and drop every other session.

    ``invalidate_other_sessions`` is accepted for older clients and copied into
    the audit event. It does not control revocation. The current session stays.
    A stored session that cannot be identified as current is revoked with the rest.
    """
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
    others = db.query(UserSession).filter(UserSession.user_id == user_id)
    if isinstance(current_sid, str) and current_sid.strip():
        others = others.filter(UserSession.session_id != current_sid)
    revoked = others.delete(synchronize_session=False)
    db.commit()
    persist_audit(
        db,
        "auth.password_changed",
        user_id=user_id,
        email=user.email,
        details={
            "invalidate_other_sessions": True,
            "client_invalidate_other_sessions": bool(req.invalidate_other_sessions),
            "revoked": revoked,
        },
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
    """Session-based login. If MFA enabled, return requires_mfa + mfa_token. Rate limited."""
    try:
        out = _login_impl(req, request, response, db)
        if isinstance(out, JSONResponse):
            return out
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
            raise HTTPException(
                status_code=503,
                detail="Database unavailable. Ensure Postgres is running and DATABASE_URL is correct.",
            )
        raise HTTPException(
            status_code=500, detail="An error occurred during sign-in. Please try again."
        )
    except Exception as e:
        logger.exception("auth.login 500: %s", e)
        raise HTTPException(
            status_code=500, detail="An error occurred during sign-in. Please try again."
        )


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
    user_query = db.query(User).filter(User.email == email)
    if db.get_bind().dialect.name != "sqlite":
        user_query = user_query.with_for_update()
    user = user_query.first()
    if not user or not verify_password(password, user.password_hash):
        record_attempt(email_key)
        persist_audit(db, "auth.login_failed")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.email_verified:
        persist_audit(db, "auth.login_unverified", user_id=user.id, email=user.email)
        return api_error_response(
            ApiError(
                code="email_not_verified",
                message="Verify your email before signing in.",
                request_id=current_request_id(request),
                retryable=False,
            ),
            403,
        )
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.workspace_id)
        .first()
    )
    if not member:
        session_id = secrets.token_urlsafe(32)
        db.add(
            UserSession(
                user_id=user.id,
                session_id=session_id,
                signing_key_id=_session_key_id(),
                user_agent=request.headers.get("user-agent"),
                ip_address=get_client_ip(request),
            )
        )
        db.commit()
        max_age = SESSION_MAX_AGE
        token = sign_session(
            user_id=user.id,
            email=user.email,
            workspace_id=0,
            role="pending",
            session_id=session_id,
            max_age_seconds=max_age,
            cookie_persistent=False,
        )
        response.set_cookie(
            key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age, persistent=False)
        )
        persist_audit(
            db, "auth.login", user_id=user.id, email=user.email, details={"needs_onboarding": True}
        )
        return {"user": _user_response(user), "needs_onboarding": True}

    mfa_row = db.query(UserMfa).filter(UserMfa.user_id == user.id).first()
    if mfa_row and mfa_reenrol_required(mfa_row.totp_secret_encrypted):
        record_decrypt_failure(
            db,
            user_id=user.id,
            stored=mfa_row.totp_secret_encrypted,
            reason="reenrol_marker",
            resource_type="user_mfa",
            resource_id=mfa_row.id,
            commit=True,
        )
        return api_error_response(
            ApiError(
                code="mfa_reset_required",
                message=(
                    "An administrator must reset multi-factor authentication before you can sign in."
                ),
                request_id=current_request_id(request),
                retryable=False,
            ),
            403,
        )
    reenrol_pending = bool(mfa_row and mfa_reenrol_pending(mfa_row.totp_secret_encrypted))
    if mfa_row and mfa_row.enabled and not reenrol_pending:
        return _mfa_challenge_response(db, user, member)

    policy_enrol = (
        not reenrol_pending
        and not (mfa_row and mfa_row.enabled)
        and _member_workspace_requires_mfa(db, member.workspace_id)
    )
    enrol_only = reenrol_pending or policy_enrol
    if enrol_only and member.suspended:
        raise HTTPException(status_code=403, detail="Active workspace membership required")
    remember = bool(req.remember_me) and not enrol_only
    policy_age = _effective_session_max_age_seconds(db, member.workspace_id, remember)
    max_age = min(300, policy_age) if enrol_only else policy_age
    audit_log("auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id)
    try:
        persist_audit(
            db, "auth.login", user_id=user.id, email=user.email, workspace_id=member.workspace_id
        )
    except Exception as e:
        logger.warning("auth.login persist_audit failed (login continues): %s", e)
    session_id = secrets.token_urlsafe(32)
    # The stored row and the signed exp must share one second. A later
    # time.time() can make reissue shorten the cookie by one second.
    created = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    row = UserSession(
        user_id=user.id,
        session_id=session_id,
        signing_key_id=_session_key_id(),
        user_agent=request.headers.get("user-agent"),
        ip_address=get_client_ip(request),
        created_at=created,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    stored = row.created_at
    stored = stored.replace(tzinfo=timezone.utc) if stored.tzinfo is None else stored
    expires_at = int(stored.timestamp()) + max_age
    token = sign_session(
        user_id=user.id,
        email=user.email,
        workspace_id=member.workspace_id,
        role="mfa_enrol" if enrol_only else member.role,
        session_id=session_id,
        expires_at=expires_at,
        mfa_enrol_only=enrol_only,
        cookie_persistent=remember,
    )
    response.set_cookie(
        key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age, persistent=remember)
    )
    result = {"user": _user_response(user), "workspace_id": member.workspace_id}
    if enrol_only:
        result["requires_mfa_enrol"] = True
    return result


@router.post("/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    """Logout - clear session cookie and remove from session store."""
    session = get_session(request)
    if session:
        try:
            enforce_session_record(session, db)
        except HTTPException:
            # Clearing an invalid cookie is still safe, but it has no authority
            # to revoke a stored session or attribute a logout audit event.
            session = None
    if session:
        sid = session.get("session_id")
        if sid:
            db.query(UserSession).filter(
                UserSession.session_id == sid, UserSession.user_id == session["user_id"]
            ).delete(synchronize_session=False)
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
    _sec = is_production_env()
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax", httponly=True, secure=_sec)
    return {"ok": True}


@router.get("/sessions")
async def list_sessions(
    session: dict = Depends(require_valid_session), db: Session = Depends(get_db)
):
    """List current user's sessions (device/location)."""
    user_id = session.get("user_id")
    current_sid = session.get("session_id")
    query = db.query(UserSession).filter(UserSession.user_id == user_id)
    if session.get("mfa_enrol_only"):
        query = query.filter(UserSession.session_id == current_sid)
    rows = query.order_by(UserSession.created_at.desc()).all()
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
async def revoke_other_sessions(
    session: dict = Depends(require_valid_session), db: Session = Depends(get_db)
):
    """Invalidate all other sessions for current user; keep current."""
    user_id = session.get("user_id")
    current_sid = session.get("session_id")
    if not current_sid:
        raise HTTPException(status_code=400, detail="Cannot revoke others for legacy session")
    deleted = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user_id,
            UserSession.session_id != current_sid,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    persist_audit(
        db,
        "auth.sessions_revoked_others",
        user_id=user_id,
        email=session.get("email"),
        details={"count": deleted},
    )
    return {"ok": True, "revoked": deleted}


@router.post("/sessions/revoke-all")
async def revoke_all_sessions(
    response: Response,
    session: dict = Depends(require_valid_session),
    db: Session = Depends(get_db),
):
    """Sign this human account out of every stored session, including this one."""
    user_id = session.get("user_id")
    if type(user_id) is not int or user_id < 1:
        # API-key contexts have no human session to revoke.
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        deleted = (
            db.query(UserSession)
            .filter(UserSession.user_id == user_id)
            .delete(synchronize_session=False)
        )
        # persist_audit commits its Session: keep the deletion and audit in
        # that same transaction, rather than acknowledging a partial revoke.
        persist_audit(
            db,
            "auth.sessions_revoked_all",
            user_id=user_id,
            email=session.get("email"),
            workspace_id=session.get("workspace_id"),
            details={"count": deleted},
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="Unable to sign out sessions. Try again."
        ) from exc
    response.delete_cookie(
        SESSION_COOKIE, path="/", samesite="lax", httponly=True, secure=is_production_env()
    )
    return {"ok": True, "revoked": deleted}


# ----- ENT-201: OAuth (Google, Microsoft) -----


def _session_key_id() -> str:
    from app.core.keys import current_session_key_id

    return current_session_key_id()


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
    from app.core.keys import sign_with_purpose

    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return sign_with_purpose("oauth_state", data)


def _oauth_verify_signed_state(state: str, expected_provider: str) -> bool:
    """Verify signed state: signature and expiry. No server-side store needed."""
    try:
        from app.core.keys import verify_with_purpose

        data = verify_with_purpose("oauth_state", state, accept_retired=True)
        if data is None:
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


def _oauth_set_session_and_redirect(
    user: User,
    workspace_id: int,
    role: str,
    db: Session,
    *,
    onboarding: bool = False,
    mfa_enrol_only: bool = False,
    max_age_seconds: int | None = None,
    cookie_persistent: bool = True,
    redirect_path: str | None = None,
) -> RedirectResponse:
    session_id = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            session_id=session_id,
            signing_key_id=_session_key_id(),
            user_agent=None,
            ip_address=None,
        )
    )
    db.commit()
    max_age = (
        max_age_seconds
        if max_age_seconds is not None
        else _session_max_age_seconds(db, workspace_id)
    )
    token = sign_session(
        user_id=user.id,
        email=user.email,
        workspace_id=workspace_id,
        role=role,
        session_id=session_id,
        max_age_seconds=max_age,
        mfa_enrol_only=mfa_enrol_only,
        cookie_persistent=cookie_persistent,
    )
    frontend = get_settings().frontend_url.rstrip("/")
    if redirect_path is not None:
        path = redirect_path
    elif onboarding:
        path = "/onboarding"
    else:
        path = "/dashboard"
    redirect_url = f"{frontend}{path}"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        **_session_cookie_kwargs(max_age, persistent=cookie_persistent),
    )
    return resp


_PROVIDER_EMAIL_UNVERIFIED = "The identity provider has not verified this email address."
_PROVIDER_LOCAL_UNVERIFIED = (
    "This email is registered but not verified. "
    "Use the verification message or reset the password before using this provider."
)


def _establish_provider_user(
    db: Session,
    *,
    provider: str,
    info: dict,
    missing_email_detail: str,
) -> User:
    """Resolve a provider identity without granting tenant membership.

    A new identity stays account-only until workspace creation or an invitation.
    An unverified provider email is rejected. An unverified local account is not
    linked, so a password chosen before verification cannot ride along.
    Configured default workspace ids are not consulted.
    """
    provider_user_id = (info.get("provider_user_id") or "").strip()
    if not provider_user_id:
        raise HTTPException(
            status_code=400, detail="The identity provider did not return an account id"
        )
    oauth_row = (
        db.query(UserOAuthAccount)
        .filter(
            UserOAuthAccount.provider == provider,
            UserOAuthAccount.provider_user_id == provider_user_id,
        )
        .first()
    )
    if oauth_row is None and provider == "microsoft" and ":" in provider_user_id:
        oid = provider_user_id.split(":", 1)[1].strip()
        if oid:
            legacy = (
                db.query(UserOAuthAccount)
                .filter(
                    UserOAuthAccount.provider == provider,
                    UserOAuthAccount.provider_user_id == oid,
                )
                .first()
            )
            if legacy is not None:
                legacy.provider_user_id = provider_user_id
                db.commit()
                oauth_row = legacy
    if oauth_row:
        user = db.query(User).filter(User.id == oauth_row.user_id).first()
        if user is None:
            raise HTTPException(status_code=400, detail=missing_email_detail)
        return user
    if not info.get("email_verified"):
        raise HTTPException(status_code=400, detail=_PROVIDER_EMAIL_UNVERIFIED)
    email = (info.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail=missing_email_detail)
    user = db.query(User).filter(User.email == email).first()
    if user is not None:
        if not user.email_verified:
            raise HTTPException(status_code=400, detail=_PROVIDER_LOCAL_UNVERIFIED)
        db.add(
            UserOAuthAccount(
                user_id=user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                email=email,
            )
        )
        db.commit()
        return user
    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        display_name=info.get("name"),
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        UserOAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
        )
    )
    db.commit()
    return user


def _audit_provider_login(
    db: Session,
    user: User,
    workspace_id: int,
    provider: str,
    *,
    onboarding: bool,
    enrol: bool = False,
) -> None:
    details: dict = {"provider": provider, "needs_onboarding": onboarding}
    if enrol:
        details["requires_mfa_enrol"] = True
    try:
        persist_audit(
            db,
            "auth.login",
            user_id=user.id,
            email=user.email,
            workspace_id=workspace_id,
            details=details,
        )
    except Exception:
        logger.warning("provider login audit failed for provider=%s", provider)


def _provider_login_response(
    db: Session, user: User, *, provider: str, state_cookie: str
) -> RedirectResponse:
    """Issue the same MFA gate as password login, then redirect the browser.

    An enabled factor lands on ``/login?mfa_token=`` with no session cookie.
    A workspace that requires MFA and has no enabled factor, and an
    administrator re-enrolment, land on ``/login?mfa_enrol=1`` with only the
    zero-permission enrolment cookie. No membership still goes to onboarding.
    """
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.workspace_id)
        .first()
    )
    if member is None:
        _audit_provider_login(db, user, 0, provider, onboarding=True)
        resp = _oauth_set_session_and_redirect(user, 0, "pending", db, onboarding=True)
        return _clear_provider_state(resp, state_cookie)

    mfa_row = db.query(UserMfa).filter(UserMfa.user_id == user.id).first()
    if mfa_row and mfa_reenrol_required(mfa_row.totp_secret_encrypted):
        record_decrypt_failure(
            db,
            user_id=user.id,
            stored=mfa_row.totp_secret_encrypted,
            reason="reenrol_marker",
            resource_type="user_mfa",
            resource_id=mfa_row.id,
            commit=True,
        )
        resp = RedirectResponse(
            url=_frontend_login_url({"error": "mfa_reset_required"}),
            status_code=302,
        )
        return _clear_provider_state(resp, state_cookie)

    reenrol_pending = bool(mfa_row and mfa_reenrol_pending(mfa_row.totp_secret_encrypted))
    if mfa_row and mfa_row.enabled and not reenrol_pending:
        raw = _store_mfa_login_token(db, user, member)
        try:
            persist_audit(
                db,
                "auth.mfa_required",
                user_id=user.id,
                email=user.email,
                workspace_id=member.workspace_id,
                details={"provider": provider},
            )
        except Exception:
            logger.warning("provider MFA audit failed for provider=%s", provider)
        resp = RedirectResponse(
            url=_frontend_login_url({"mfa_token": raw}),
            status_code=302,
        )
        return _clear_provider_state(resp, state_cookie)

    policy_enrol = (
        not reenrol_pending
        and not (mfa_row and mfa_row.enabled)
        and _member_workspace_requires_mfa(db, member.workspace_id)
    )
    enrol_only = reenrol_pending or policy_enrol
    if enrol_only and member.suspended:
        resp = RedirectResponse(
            url=_frontend_login_url({"error": "membership_required"}),
            status_code=302,
        )
        return _clear_provider_state(resp, state_cookie)

    _audit_provider_login(
        db,
        user,
        member.workspace_id,
        provider,
        onboarding=False,
        enrol=enrol_only,
    )
    if enrol_only:
        policy_age = _session_max_age_seconds(db, member.workspace_id)
        resp = _oauth_set_session_and_redirect(
            user,
            member.workspace_id,
            "mfa_enrol",
            db,
            mfa_enrol_only=True,
            max_age_seconds=min(300, policy_age),
            cookie_persistent=False,
            redirect_path="/login?mfa_enrol=1",
        )
    else:
        resp = _oauth_set_session_and_redirect(
            user, member.workspace_id, member.role, db, onboarding=False
        )
    return _clear_provider_state(resp, state_cookie)


@router.get("/oauth/providers")
def oauth_providers():
    """Return which OAuth/SSO providers are configured (for login page buttons). SSO is included when OIDC is enabled."""
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
    """Redirect to Google OAuth consent. Uses signed state so callback works even if cookie is lost on redirect."""
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
    """Handle Google OAuth callback; find or create user, issue session. Accepts signed state or cookie."""
    logger.info(
        "oauth_google_callback entry code=%s state_len=%s",
        bool(code),
        len(state) if state else 0,
        extra={"step": "callback_entry"},
    )
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
            raise HTTPException(
                status_code=503, detail="Database unavailable. Please try again later."
            )
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )
    except Exception as e:
        logger.exception("oauth_google_callback 500: %s", e)
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )


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
            persist_audit(
                db, "auth.oauth_failed", details={"provider": "google", "reason": "invalid_state"}
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired state. Start sign-in from the app login page.",
        )
    redirect_uri = _oauth_redirect_uri("google")
    info = await google_exchange_code(code, redirect_uri)
    if not info:
        logger.warning("oauth_google_callback google_exchange_code returned None")
        try:
            persist_audit(
                db,
                "auth.oauth_failed",
                details={"provider": "google", "reason": "token_exchange_failed"},
            )
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Failed to get user info from Google")
    if not (info.get("provider_user_id") or "").strip():
        logger.warning("oauth_google_callback profile missing user identifier (id/sub)")
        raise HTTPException(
            status_code=400, detail="Google did not return a user identifier (id or sub)"
        )
    logger.info(
        "oauth_google_callback got profile email_ok=%s",
        bool(info.get("email")),
        extra={"step": "after_exchange"},
    )
    user = _establish_provider_user(
        db,
        provider="google",
        info=info,
        missing_email_detail="Google did not provide an email",
    )
    logger.info("oauth_google_callback resolved user_id=%s", user.id, extra={"step": "user_ok"})
    try:
        resp = _provider_login_response(
            db, user, provider="google", state_cookie=OAUTH_STATE_COOKIE
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("oauth_google_callback session redirect failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )
    logger.info("oauth_google_callback success", extra={"step": "callback_done"})
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
        logger.warning(
            "oauth_github_callback missing code or state", extra={"step": "callback_params"}
        )
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
            raise HTTPException(
                status_code=503, detail="Database unavailable. Please try again later."
            )
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )
    except Exception as e:
        logger.exception("oauth_github_callback 500: %s", e)
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )


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
            persist_audit(
                db, "auth.oauth_failed", details={"provider": "github", "reason": "invalid_state"}
            )
        except Exception:
            pass
        logger.warning(
            "oauth_github_callback state invalid or expired", extra={"step": "callback_state"}
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired state. Start sign-in from the app login page.",
        )
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
    user = _establish_provider_user(
        db,
        provider="github",
        info=info,
        missing_email_detail=(
            "GitHub did not provide an email (enable user:email scope or set public email)"
        ),
    )
    logger.info(
        "oauth_github_callback user_ok user_id=%s", user.id, extra={"step": "user_resolved"}
    )
    return _provider_login_response(db, user, provider="github", state_cookie=OAUTH_STATE_COOKIE)


@router.get("/oauth/microsoft")
async def oauth_microsoft_start(request: Request, response: Response):
    """Redirect to Microsoft OAuth consent."""
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
    """Handle Microsoft OAuth callback; find or create user, issue session."""
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    if not cookie or "|" not in cookie:
        raise HTTPException(status_code=400, detail="Invalid state")
    cookie_state, provider = cookie.strip().split("|", 1)
    if provider != "microsoft" or cookie_state != state:
        try:
            persist_audit(
                db,
                "auth.oauth_failed",
                details={"provider": "microsoft", "reason": "invalid_state"},
            )
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
            raise HTTPException(
                status_code=503, detail="Database unavailable. Please try again later."
            )
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )
    except Exception as e:
        logger.exception("oauth_microsoft_callback 500: %s", e)
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )


async def _oauth_microsoft_callback_impl(request: Request, code: str, db: Session):
    """Inner Microsoft OAuth callback (wrapped by route for safe 500/503)."""
    redirect_uri = _oauth_redirect_uri("microsoft")
    info = await microsoft_exchange_code(code, redirect_uri)
    if not info or not info.get("provider_user_id"):
        raise HTTPException(status_code=400, detail="Failed to get user info from Microsoft")
    user = _establish_provider_user(
        db,
        provider="microsoft",
        info=info,
        missing_email_detail="Microsoft did not provide an email",
    )
    return _provider_login_response(db, user, provider="microsoft", state_cookie=OAUTH_STATE_COOKIE)


# ----- ENT-203: Enterprise OIDC SSO; ENT-204: JIT provisioning -----

SSO_STATE_COOKIE = "sso_state"
SSO_STATE_MAX_AGE = 600


@router.get("/sso")
async def sso_start(request: Request, response: Response):
    """Redirect to configured OIDC IdP. This is the SSO entry point."""
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
    """OIDC callback: exchange code, resolve the account, and issue a session."""
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
            raise HTTPException(
                status_code=503, detail="Database unavailable. Please try again later."
            )
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )
    except Exception as e:
        logger.exception("sso_callback 500: %s", e)
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )


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
    user = _establish_provider_user(
        db,
        provider="oidc",
        info=info,
        missing_email_detail="SSO did not provide an email",
    )
    return _provider_login_response(db, user, provider="oidc_sso", state_cookie=SSO_STATE_COOKIE)


# ----- ENT-205: id.me; ENT-206: hardened callback -----

IDME_STATE_COOKIE = "idme_state"
IDME_STATE_MAX_AGE = 600


@router.get("/idme")
async def idme_start(request: Request, response: Response):
    """Redirect to id.me authorization."""
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
    """id.me callback. Strict state validation, static redirect URI, server-side token only."""
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
            raise HTTPException(
                status_code=503, detail="Database unavailable. Please try again later."
            )
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )
    except Exception as e:
        logger.exception("idme_callback 500: %s", e)
        raise HTTPException(
            status_code=500, detail="Sign-in could not be completed. Please try again."
        )


async def _idme_callback_impl(request: Request, code: str, db: Session):
    """Inner id.me callback (wrapped by route for safe 500/503)."""
    redirect_uri = _idme_redirect_uri()
    info = await idme_exchange_code(code, redirect_uri)
    if not info or not info.get("provider_user_id"):
        raise HTTPException(status_code=400, detail="id.me user info failed")
    user = _establish_provider_user(
        db,
        provider="idme",
        info=info,
        missing_email_detail="id.me did not provide an email",
    )
    return _provider_login_response(db, user, provider="idme", state_cookie=IDME_STATE_COOKIE)


# Suspicious actions we surface as alerts (WEB-211)
SUSPICIOUS_ACTIONS = frozenset(
    {
        "auth.mfa_verify_failed",
        "auth.mfa_confirm_failed",
        "auth.mfa_disable_failed",
        "auth.login_failed",  # when user_id present, e.g. no_workspace
    }
)


@router.get("/alerts")
async def list_alerts(
    session: dict = Depends(require_valid_session), db: Session = Depends(get_db)
):
    """Recent suspicious auth events for current user (in-app alerts)."""
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

        cr = (
            db.query(CustomRole)
            .filter(CustomRole.workspace_id == workspace_id, CustomRole.name == role)
            .first()
        )
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
    """Return current user, workspace, workspaces list, role, and permissions."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = verify_token(cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    enforce_session_record(session, db)
    enforce_mfa_enrol_session(request, session, db)
    session = resolve_current_membership(request, session, db)
    user_id = session.get("user_id")
    workspace_id = session.get("workspace_id")
    role = session.get("role")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if workspace_id == 0 and role == "pending":
        return {
            "id": user.id,
            "email": user.email or "",
            "display_name": getattr(user, "display_name", None) or "User",
            "workspace_id": 0,
            "workspace_name": "",
            "workspace_slug": "",
            "role": "pending",
            "workspaces": [],
            "permissions": {
                "can_edit": False,
                "can_review": False,
                "can_admin": False,
                "can_export": False,
            },
            "needs_onboarding": True,
            "mfa_enrolled": False,
            "mfa_required_for_workspace": False,
            "workspace_auth_policy": {"mfa_required": False, "session_max_age_seconds": None},
        }
    current_ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if session.get("mfa_enrol_only"):
        workspace = {
            "id": workspace_id,
            "name": current_ws.name if current_ws else "Workspace",
            "slug": current_ws.slug if current_ws else "",
            "role": "mfa_enrol",
        }
        return {
            **_user_response(user),
            "workspace_id": workspace_id,
            "workspace_name": workspace["name"],
            "workspace_slug": workspace["slug"],
            "role": "mfa_enrol",
            "workspaces": [workspace],
            "permissions": {
                name: False for name in ("can_edit", "can_review", "can_admin", "can_export")
            },
            "needs_onboarding": False,
            "mfa_enrolled": False,
            "mfa_required_for_workspace": True,
            "workspace_auth_policy": {"mfa_required": True, "session_max_age_seconds": 300},
        }
    memberships = (
        db.query(WorkspaceMember, Workspace)
        .join(Workspace, WorkspaceMember.workspace_id == Workspace.id)
        .filter(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.id)
        .all()
    )
    workspaces = [
        {
            "id": ws.id,
            "name": getattr(ws, "name", "Workspace"),
            "slug": getattr(ws, "slug", ""),
            "role": mem.role,
        }
        for mem, ws in memberships
    ]
    from app.models import Subscription

    active_sub = (
        db.query(Subscription)
        .filter(
            Subscription.workspace_id == workspace_id,
            Subscription.status.in_(["active", "trialing"]),
        )
        .first()
    )

    mfa_row = (
        db.query(UserMfa).filter(UserMfa.user_id == user_id, UserMfa.enabled.is_(True)).first()
    )
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
            "session_max_age_seconds": getattr(current_ws, "session_max_age_seconds", None)
            if current_ws
            else None,
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
    """Switch active workspace; reissue session with new workspace_id and role."""
    # The current workspace's cutoff does not block leaving it. The target
    # check below still rejects a workspace whose sessions were revoked.
    session = await require_session_leaving_workspace(request, db)
    user_id = session.get("user_id")
    email = session.get("email", "")
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == body.workspace_id,
        )
        .populate_existing()
        .first()
    )
    if not member or member.suspended:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    deadline = enforce_session_record({**session, "workspace_id": member.workspace_id}, db)
    expires_at = int(deadline)
    if expires_at <= time.time():
        raise HTTPException(status_code=401, detail="Session expired")
    ws = db.query(Workspace).filter(Workspace.id == body.workspace_id).first()
    existing_session_id = session.get("session_id")
    if not existing_session_id:
        raise HTTPException(status_code=400, detail="Cannot switch workspace for legacy session")
    try:
        factor = db.query(UserMfa).filter(UserMfa.user_id == user_id).populate_existing().first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Session policy unavailable") from exc
    # Same rule as login: a required workspace with no enabled factor yields only
    # the five-minute, non-persistent enrol session. An enabled factor whose
    # session never completed a challenge gets the login challenge and no role.
    if workspace_requires_unmet_mfa(db, user_id, member.workspace_id, factor):
        now = int(time.time())
        policy_age = _session_max_age_seconds(db, member.workspace_id)
        expires_at = min(expires_at, now + min(300, policy_age))
        if expires_at <= now:
            raise HTTPException(status_code=401, detail="Session expired")
        token = sign_session(
            user_id=user_id,
            email=email,
            workspace_id=member.workspace_id,
            role="mfa_enrol",
            session_id=existing_session_id,
            expires_at=expires_at,
            mfa_enrol_only=True,
            cookie_persistent=False,
        )
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            **_session_cookie_kwargs(expires_at - now, persistent=False),
        )
        persist_audit(
            db,
            "auth.workspace_switch",
            user_id=user_id,
            email=email,
            workspace_id=member.workspace_id,
            details={
                "workspace_name": ws.name if ws else "Default",
                "role": "mfa_enrol",
                "requires_mfa_enrol": True,
            },
        )
        return {
            "workspace_id": member.workspace_id,
            "workspace_name": ws.name if ws else "Default",
            "workspace_slug": getattr(ws, "slug", "") if ws else "",
            "role": "mfa_enrol",
            "requires_mfa_enrol": True,
            "mfa_required_for_workspace": True,
        }
    if bool(ws and ws.mfa_required) and _enabled_mfa_factor(factor):
        if not _session_mfa_satisfied(db, user_id, existing_session_id):
            user = db.query(User).filter(User.id == user_id).first()
            if user is None:
                raise HTTPException(status_code=401, detail="User not found")
            return _mfa_challenge_response(db, user, member, details={"source": "switch-workspace"})
    persistent = session.get("cookie_persistent") is True
    token = sign_session(
        user_id=user_id,
        email=email,
        workspace_id=member.workspace_id,
        role=member.role,
        session_id=existing_session_id,
        expires_at=expires_at,
        cookie_persistent=persistent,
    )
    max_age = expires_at - int(time.time())
    if max_age <= 0:
        raise HTTPException(status_code=401, detail="Session expired")
    response.set_cookie(
        key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age, persistent=persistent)
    )
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
        "mfa_required_for_workspace": _mfa_required_for_workspace_flag(ws, factor),
    }


# ----- AUTH-208: Accept invite (public endpoint) -----


@router.post("/verify-invite-code")
def verify_invite_code(
    req: VerifyInviteCodeRequest, request: Request, db: Session = Depends(get_db)
):
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
    """Accept workspace invite by token. New user: set password and create account. Existing user: confirm email and add to workspace.
    For new invites, obtain token via POST /verify-invite-code. Legacy invites (no verification code) may still use a token from an old link."""
    if not req.token or not req.token.strip():
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    h = _token_hash(req.token.strip())
    inv = db.query(Invite).filter(Invite.token_hash == h).first()
    if not inv:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    # Lock the invite before creating the account. A second submit of this token
    # waits, re-reads, and finds no row.
    inv = _for_update(db, db.query(Invite).filter(Invite.id == inv.id).populate_existing()).first()
    if not inv:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    _after_row_locked("accept-invite")
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
        existing_mem = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == inv.workspace_id,
                WorkspaceMember.user_id == user.id,
            )
            .first()
        )
        if existing_mem:
            db.delete(inv)
            db.commit()
            raise HTTPException(
                status_code=400, detail="You are already a member of this workspace"
            )
        # A password set before the address was verified must not survive the invite.
        if not user.email_verified:
            locked = db.query(User).filter(User.id == user.id)
            if db.get_bind().dialect.name != "sqlite":
                locked = locked.with_for_update()
            user = locked.populate_existing().one()
        if not user.email_verified:
            password = (req.password or "").strip()
            if len(password) < 6:
                raise HTTPException(
                    status_code=400,
                    detail="Set a password to claim this account (at least 6 characters)",
                )
            user.password_hash = hash_password(password)
            _delete_user_sessions(db, user.id)
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            ).delete(synchronize_session=False)
            _delete_verification_tokens(db, user.id)
            db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).delete(
                synchronize_session=False
            )
            db.query(MfaLoginToken).filter(MfaLoginToken.user_id == user.id).delete(
                synchronize_session=False
            )
            db.query(UserMfa).filter(UserMfa.user_id == user.id).delete(synchronize_session=False)
            db.query(UserOAuthAccount).filter(UserOAuthAccount.user_id == user.id).delete(
                synchronize_session=False
            )
        user.email_verified = True
        mem = WorkspaceMember(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role)
        db.add(mem)
        db.delete(inv)
        db.commit()
        persist_audit(
            db,
            "auth.invite_accepted",
            user_id=user.id,
            email=email,
            workspace_id=inv.workspace_id,
            details={"role": inv.role},
        )
        return {"message": "You have joined the workspace. You can sign in."}
    if not req.password or len(req.password.strip()) < 6:
        raise HTTPException(
            status_code=400, detail="Set a password to create your account (at least 6 characters)"
        )
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
    persist_audit(
        db,
        "auth.invite_accepted_new_user",
        user_id=user.id,
        email=email,
        workspace_id=inv.workspace_id,
        details={"role": inv.role},
    )
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
    existing = (
        db.query(UserMfa)
        .filter(UserMfa.user_id == user_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if existing and existing.enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    pending_existing = bool(existing and mfa_reenrol_pending(existing.totp_secret_encrypted))
    if session.get("mfa_enrol_only") and not pending_existing:
        allowed = workspace_requires_unmet_mfa(db, user_id, session.get("workspace_id"), existing)
        if not allowed:
            raise HTTPException(status_code=401, detail="MFA enrollment session expired")
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(
        secret,
        reenrol_pending=bool(existing and mfa_reenrol_pending(existing.totp_secret_encrypted)),
    )
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
async def mfa_confirm(
    req: MfaConfirmRequest, request: Request, response: Response, db: Session = Depends(get_db)
):
    """Verify TOTP code and enable MFA; generate and return recovery codes (one-time display)."""
    session = await require_session(request, db)
    user_id = session.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    row = (
        db.query(UserMfa)
        .filter(UserMfa.user_id == user_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Start MFA setup first")
    if row.enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    pending = mfa_reenrol_pending(row.totp_secret_encrypted)
    policy_enrol = bool(
        session.get("mfa_enrol_only")
        and not pending
        and workspace_requires_unmet_mfa(db, user_id, session.get("workspace_id"), row)
    )
    if session.get("mfa_enrol_only") and not (pending or policy_enrol):
        raise HTTPException(status_code=401, detail="MFA enrollment session expired")
    member = None
    old_session = None
    upgrade = pending or policy_enrol
    if upgrade:
        if pending and not session.get("mfa_enrol_only"):
            raise HTTPException(status_code=403, detail="Sign in again to complete MFA enrollment")
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.workspace_id == session.get("workspace_id"),
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
        if not member or member.suspended:
            raise HTTPException(status_code=403, detail="Active workspace membership required")
        old_session = (
            db.query(UserSession)
            .filter(
                UserSession.user_id == user_id,
                UserSession.session_id == session.get("session_id"),
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
        if not old_session:
            raise HTTPException(status_code=401, detail="MFA enrollment session expired")
        max_age = _session_max_age_seconds(db, member.workspace_id)
    try:
        secret = decrypt_mfa_for_user(
            db,
            user_id=user_id,
            encrypted=row.totp_secret_encrypted,
            resource_id=row.id,
        )
    except (KeyErrorSafe, MfaReenrolRequired):
        raise HTTPException(status_code=400, detail="Invalid code")
    if not verify_totp(secret, (req.code or "").strip()):
        persist_audit(db, "auth.mfa_confirm_failed", user_id=user_id, email=user.email)
        raise HTTPException(status_code=400, detail="Invalid code")
    row.enabled = True
    new_session_id = None
    if pending:
        row.totp_secret_encrypted = encrypt_totp_secret(secret)
    if upgrade:
        db.delete(old_session)
        new_session_id = secrets.token_urlsafe(32)
        db.add(
            UserSession(
                user_id=user_id,
                session_id=new_session_id,
                signing_key_id=_session_key_id(),
                user_agent=request.headers.get("user-agent"),
                ip_address=get_client_ip(request),
                mfa_satisfied=True,
            )
        )
    recovery_codes_raw = []
    for _ in range(10):
        code = secrets.token_hex(4).upper()
        code = f"{code[:4]}-{code[4:]}"  # XXXXX-XXXX format
        recovery_codes_raw.append(code)
        db.add(MfaRecoveryCode(user_id=user_id, code_hash=_recovery_code_hash(code)))
    db.commit()
    if new_session_id:
        token = sign_session(
            user_id,
            user.email,
            member.workspace_id,
            member.role,
            session_id=new_session_id,
            max_age_seconds=max_age,
            cookie_persistent=False,
        )
        response.set_cookie(
            key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age, persistent=False)
        )
    persist_audit(db, "auth.mfa_enabled", user_id=user_id, email=user.email)
    return {"recovery_codes": recovery_codes_raw}


@router.post("/mfa/verify-login")
def mfa_verify_login(
    req: MfaVerifyLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
):
    """Complete login after MFA: accept mfa_token + code (TOTP or recovery), issue session."""
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
    mfa_row = (
        db.query(UserMfa).filter(UserMfa.user_id == user.id, UserMfa.enabled.is_(True)).first()
    )
    if not mfa_row:
        db.delete(mlt)
        db.commit()
        raise HTTPException(status_code=400, detail="MFA not enabled")
    if mfa_reenrol_required(mfa_row.totp_secret_encrypted):
        db.delete(mlt)
        record_decrypt_failure(
            db,
            user_id=user.id,
            stored=mfa_row.totp_secret_encrypted,
            reason="reenrol_marker",
            resource_type="user_mfa",
            resource_id=mfa_row.id,
            commit=True,
        )
        return api_error_response(
            ApiError(
                code="mfa_reset_required",
                message=(
                    "An administrator must reset multi-factor authentication before you can sign in."
                ),
                request_id=current_request_id(request),
                retryable=False,
            ),
            403,
        )
    remember = bool(req.remember_me)
    max_age = _effective_session_max_age_seconds(db, mlt.workspace_id, remember)
    verified = False
    if len(code) == 6 and code.isdigit():
        try:
            secret = decrypt_mfa_for_user(
                db,
                user_id=user.id,
                encrypted=mfa_row.totp_secret_encrypted,
                resource_id=mfa_row.id,
            )
        except (KeyErrorSafe, MfaReenrolRequired):
            verified = False
        else:
            verified = verify_totp(secret, code)
    if not verified:
        code_hash = _recovery_code_hash(code)
        rc = (
            db.query(MfaRecoveryCode)
            .filter(
                MfaRecoveryCode.user_id == user.id,
                MfaRecoveryCode.code_hash == code_hash,
                MfaRecoveryCode.used_at.is_(None),
            )
            .first()
        )
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
    db.add(
        UserSession(
            user_id=user.id,
            session_id=session_id,
            signing_key_id=_session_key_id(),
            user_agent=request.headers.get("user-agent"),
            ip_address=get_client_ip(request),
            mfa_satisfied=True,
        )
    )
    db.commit()
    audit_log("auth.login", user_id=user.id, email=user.email, workspace_id=mlt.workspace_id)
    persist_audit(
        db, "auth.login", user_id=user.id, email=user.email, workspace_id=mlt.workspace_id
    )
    token = sign_session(
        user_id=user.id,
        email=user.email,
        workspace_id=mlt.workspace_id,
        role=mlt.role,
        session_id=session_id,
        max_age_seconds=max_age,
        cookie_persistent=remember,
    )
    response.set_cookie(
        key=SESSION_COOKIE, value=token, **_session_cookie_kwargs(max_age, persistent=remember)
    )
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
