"""Real routes/dependencies against isolated SQLite rows, not PG release qualification.

These regressions complement the existing PostgreSQL HTTP tests. No auth, key,
password or TOTP implementation is mocked and no provider is called.
"""

import asyncio
import secrets
from datetime import datetime, timedelta
from http.cookies import SimpleCookie

import pyotp
import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable
from sqlalchemy.exc import OperationalError

from app.api.routes import auth, members
from app.core.auth_deps import (
    require_can_admin,
    require_can_edit,
    require_session,
    require_valid_session_optional,
)
from app.core.mfa import encrypt_totp_secret
from app.core.key_rotation import _rotate_column
from app.core.keys import open_sealed
from app.core.password import hash_password
from app.core.session import sign_session, verify_token
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    MfaLoginToken,
    MfaRecoveryCode,
    Subscription,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)

PASSWORD = secrets.token_urlsafe(24)


def request(path, token=None, method="POST"):
    headers = [(b"cookie", f"tc_session={token}".encode())] if token else []
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "client": ("127.0.0.71", 1777),
            "query_string": b"",
        }
    )


def cookie(response):
    parsed = SimpleCookie()
    parsed.load(response.headers["set-cookie"])
    return parsed["tc_session"].value


@pytest.fixture
def isolated_db(monkeypatch):
    for name in ("SESSION_KEYRING", "MFA_KEYRING"):
        monkeypatch.delenv(name, raising=False)
    from app.core import rate_limit

    rate_limit._store.clear()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for model in (
            User,
            Workspace,
            WorkspaceMember,
            UserSession,
            UserMfa,
            MfaRecoveryCode,
            MfaLoginToken,
            AuditEvent,
            ApiKey,
            CustomRole,
            Subscription,
        ):
            connection.execute(CreateTable(model.__table__))
    with Session(engine) as db:
        db.add_all(
            [
                Workspace(
                    id=1, name="Synthetic workspace", slug="synthetic-reenrol", mfa_required=True
                ),
                User(
                    id=1, email="synthetic-admin@example.com", password_hash=hash_password(PASSWORD)
                ),
                User(
                    id=2,
                    email="synthetic-target@example.com",
                    password_hash=hash_password(PASSWORD),
                ),
                WorkspaceMember(workspace_id=1, user_id=1, role="admin"),
                WorkspaceMember(workspace_id=1, user_id=2, role="editor"),
                UserMfa(user_id=2, enabled=True, totp_secret_encrypted="reenrol.synthetic"),
            ]
        )
        db.commit()
        yield db
    engine.dispose()
    rate_limit._store.clear()


def reset(db):
    return asyncio.run(
        members.admin_clear_mfa_reenrol(2, db, {"workspace_id": 1, "user_id": 1, "role": "admin"})
    )


def login(db):
    response = Response()
    body = auth._login_impl(
        auth.LoginRequest(email="synthetic-target@example.com", password=PASSWORD),
        request("/api/auth/login"),
        response,
        db,
    )
    return body, cookie(response)


@pytest.mark.parametrize("change", ["demoted", "suspended", "removed"])
def test_changed_membership_cannot_reset_using_old_admin_cookie(isolated_db, change):
    db = isolated_db
    actor = db.query(WorkspaceMember).filter_by(user_id=1).one()
    if change == "demoted":
        actor.role = "reviewer"
    elif change == "suspended":
        actor.suspended = True
    else:
        db.delete(actor)
    db.add(UserSession(user_id=1, session_id="synthetic-stale-admin"))
    db.commit()
    token = sign_session(
        1, "synthetic-admin@example.com", 1, "admin", session_id="synthetic-stale-admin"
    )
    req = request("/api/members/clear-mfa-reenrol/2", token)
    with pytest.raises(HTTPException) as denied:
        actor = asyncio.run(require_can_admin(req, db))
        asyncio.run(members.admin_clear_mfa_reenrol(2, db, actor))
    assert denied.value.status_code == 403
    assert db.query(UserMfa).filter_by(user_id=2).one().totp_secret_encrypted == "reenrol.synthetic"


def test_reset_login_cannot_use_business_optional_or_workspace_switch_auth(isolated_db):
    db = isolated_db
    reset(db)
    _, token = login(db)
    for path, method in [
        ("/api/documents", "GET"),
        ("/api/auth/switch-workspace", "POST"),
        ("/api/auth/mfa/disable", "POST"),
        ("/api/auth/sessions/revoke-others", "POST"),
    ]:
        with pytest.raises(HTTPException) as denied:
            asyncio.run(require_session(request(path, token, method), db))
        assert denied.value.status_code in (401, 403)
    assert (
        asyncio.run(require_valid_session_optional(request("/api/documents", token, "GET"), db))
        is None
    )
    info = auth.me(request("/api/auth/me", token, "GET"), db)
    assert not any(info["permissions"].values())
    assert info["mfa_required_for_workspace"] is True


def test_reset_invalidates_existing_sessions_and_blocks_legacy_cookie(isolated_db):
    db = isolated_db
    db.add(UserSession(user_id=2, session_id="synthetic-before-reset"))
    db.add(
        MfaLoginToken(
            user_id=2,
            workspace_id=1,
            role="editor",
            token_hash="synthetic-before-reset-challenge",
            expires_at=datetime.now() + timedelta(minutes=5),
        )
    )
    db.add(MfaRecoveryCode(user_id=2, code_hash="synthetic-before-reset-recovery"))
    db.commit()
    old = sign_session(
        2, "synthetic-target@example.com", 1, "editor", session_id="synthetic-before-reset"
    )
    legacy = sign_session(2, "synthetic-target@example.com", 1, "editor")
    reset(db)
    for token in (old, legacy):
        with pytest.raises(HTTPException):
            asyncio.run(require_can_edit(request("/api/documents", token), db))
        assert (
            asyncio.run(require_valid_session_optional(request("/api/documents", token), db))
            is None
        )
    assert db.query(UserSession).filter_by(user_id=2).count() == 0
    assert db.query(MfaLoginToken).filter_by(user_id=2).count() == 0
    assert db.query(MfaRecoveryCode).filter_by(user_id=2).count() == 0


def test_normal_disabled_optional_mfa_preserves_existing_login_behavior(isolated_db):
    row = isolated_db.query(UserMfa).filter_by(user_id=2).one()
    row.enabled = False
    row.totp_secret_encrypted = encrypt_totp_secret(pyotp.random_base32())
    isolated_db.commit()
    _, token = login(isolated_db)
    assert (
        asyncio.run(require_can_edit(request("/api/documents", token), isolated_db))["role"]
        == "editor"
    )


def test_confirm_replaces_only_pending_session_after_valid_code_and_uses_current_role(isolated_db):
    db = isolated_db
    reset(db)
    _, token = login(db)
    with pytest.raises(HTTPException):
        asyncio.run(require_can_edit(request("/api/documents", token), db))
    setup = asyncio.run(auth.mfa_setup(request("/api/auth/mfa/setup", token), db))
    with pytest.raises(HTTPException):
        asyncio.run(
            auth.mfa_confirm(
                auth.MfaConfirmRequest(code="invalid"),
                request("/api/auth/mfa/confirm", token),
                response=Response(),
                db=db,
            )
        )
    assert not db.query(UserMfa).filter_by(user_id=2).one().enabled
    assert db.query(UserSession).filter_by(user_id=2).count() == 1
    db.query(WorkspaceMember).filter_by(user_id=2).one().role = "reviewer"
    db.commit()
    response = Response()
    result = asyncio.run(
        auth.mfa_confirm(
            auth.MfaConfirmRequest(code=pyotp.TOTP(setup["secret"]).now()),
            request("/api/auth/mfa/confirm", token),
            response=response,
            db=db,
        )
    )
    assert len(result["recovery_codes"]) == 10
    fresh = cookie(response)
    assert verify_token(fresh)["role"] == "reviewer"
    with pytest.raises(HTTPException) as denied:
        asyncio.run(require_can_edit(request("/api/documents", fresh), db))
    assert denied.value.status_code == 403
    assert db.query(UserSession).filter_by(user_id=2).count() == 1
    assert verify_token(fresh)["session_id"] != verify_token(token)["session_id"]
    with pytest.raises(HTTPException):
        asyncio.run(require_session(request("/api/auth/mfa/status", token, "GET"), db))


def test_suspension_before_confirmation_does_not_enable_factor_or_grant_session(isolated_db):
    db = isolated_db
    reset(db)
    _, token = login(db)
    with pytest.raises(HTTPException):
        asyncio.run(require_can_edit(request("/api/documents", token), db))
    setup = asyncio.run(auth.mfa_setup(request("/api/auth/mfa/setup", token), db))
    db.query(WorkspaceMember).filter_by(user_id=2).one().suspended = True
    db.commit()
    response = Response()
    with pytest.raises(HTTPException) as denied:
        asyncio.run(
            auth.mfa_confirm(
                auth.MfaConfirmRequest(code=pyotp.TOTP(setup["secret"]).now()),
                request("/api/auth/mfa/confirm", token),
                response=response,
                db=db,
            )
        )
    assert denied.value.status_code == 403
    assert "set-cookie" not in response.headers
    assert not db.query(UserMfa).filter_by(user_id=2).one().enabled


def test_reenrol_marker_survives_setup_and_key_reencryption(isolated_db, monkeypatch):
    db = isolated_db
    monkeypatch.setenv("MFA_KEYRING", "first:synthetic-first-mfa-key")
    reset(db)
    _, token = login(db)
    setup = asyncio.run(auth.mfa_setup(request("/api/auth/mfa/setup", token), db))
    row = db.query(UserMfa).filter_by(user_id=2).one()
    assert row.totp_secret_encrypted.startswith("reenrol-pending!.first.")
    monkeypatch.setenv(
        "MFA_KEYRING", "second:synthetic-second-mfa-key,first:synthetic-first-mfa-key"
    )
    result = _rotate_column(
        db,
        [row],
        "mfa",
        lambda item: item.totp_secret_encrypted,
        lambda item, value: setattr(item, "totp_secret_encrypted", value),
        dry_run=False,
        on_fail=None,
    )
    assert result["reencrypted"] == 1
    assert row.totp_secret_encrypted.startswith("reenrol-pending!.second.")
    assert open_sealed("mfa", row.totp_secret_encrypted) == setup["secret"]
    with pytest.raises(HTTPException):
        asyncio.run(require_can_edit(request("/api/documents", token), db))


def test_enrollment_session_list_is_limited_to_current_session(isolated_db):
    db = isolated_db
    reset(db)
    _, first = login(db)
    _, second = login(db)
    req = request("/api/auth/sessions", first, "GET")
    context = asyncio.run(require_session(req, db))
    result = asyncio.run(auth.list_sessions(context, db))
    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["current"] is True
    assert verify_token(first)["session_id"] != verify_token(second)["session_id"]


def test_confirmation_commit_failure_leaves_pending_state_and_no_new_cookie(
    isolated_db, monkeypatch
):
    db = isolated_db
    reset(db)
    _, token = login(db)
    setup = asyncio.run(auth.mfa_setup(request("/api/auth/mfa/setup", token), db))
    response = Response()

    def failed_commit():
        raise OperationalError("synthetic transaction failure", {}, None)

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", failed_commit)
        with pytest.raises(OperationalError):
            asyncio.run(
                auth.mfa_confirm(
                    auth.MfaConfirmRequest(code=pyotp.TOTP(setup["secret"]).now()),
                    request("/api/auth/mfa/confirm", token),
                    response=response,
                    db=db,
                )
            )
    db.rollback()
    assert "set-cookie" not in response.headers
    row = db.query(UserMfa).filter_by(user_id=2).one()
    assert not row.enabled
    assert row.totp_secret_encrypted.startswith("reenrol-pending!.")
    assert db.query(UserSession).filter_by(user_id=2).count() == 1
    assert (
        db.query(UserSession).filter_by(user_id=2).one().session_id
        == verify_token(token)["session_id"]
    )
    assert db.query(MfaRecoveryCode).filter_by(user_id=2).count() == 0
