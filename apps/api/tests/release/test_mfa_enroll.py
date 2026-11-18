"""Provider and password login must honor an enabled factor and workspace MFA policy.

SQLite runs are the local control. The same cases run on migrated PostgreSQL.
Token exchange is mocked; the callback, MFA token and session cookie are real.
"""

from __future__ import annotations

import secrets
from contextlib import ExitStack
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from http.cookies import SimpleCookie

import pyotp
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes import auth
from app.api.routes.auth import _oauth_create_signed_state, _recovery_code_hash
from app.core import auth_deps, rate_limit
from app.core.database import get_db
from app.core.mfa import encrypt_totp_secret, generate_totp_secret
from app.core.password import hash_password
from app.core.session import verify_token
from app.models import (
    AuditEvent,
    MfaLoginToken,
    MfaRecoveryCode,
    Subscription,
    User,
    UserMfa,
    UserOAuthAccount,
    UserSession,
    Workspace,
    WorkspaceMember,
)

pytestmark = pytest.mark.integration

PATHS = ("password", "google", "github", "microsoft", "oidc", "idme")
PASSWORD = secrets.token_urlsafe(24)
ADMIN_PERMS = {
    "can_edit": True,
    "can_review": True,
    "can_export": True,
    "can_admin": True,
}
ZERO_PERMS = {name: False for name in ADMIN_PERMS}
MODELS = (
    User,
    Workspace,
    WorkspaceMember,
    UserSession,
    UserMfa,
    MfaRecoveryCode,
    MfaLoginToken,
    UserOAuthAccount,
    AuditEvent,
    Subscription,
)


def counts(db: Session) -> dict[str, int]:
    return {
        model.__tablename__: int(db.scalar(select(func.count()).select_from(model)) or 0)
        for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def enroll_state(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        db = request.getfixturevalue("db_session")
        engine = db.get_bind()
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            for model in MODELS:
                connection.execute(CreateTable(model.__table__))
        db = Session(engine)
    before = counts(db)
    suffix = secrets.token_hex(8)
    workspace = Workspace(name=f"MFA {suffix}", slug=f"mfa-{suffix}", mfa_required=False)
    user = User(
        email=f"mfa-{suffix}@example.test",
        password_hash=hash_password(PASSWORD),
        email_verified=True,
    )
    db.add_all([workspace, user])
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin"))
    db.commit()
    user_id, workspace_id, email = user.id, workspace.id, user.email
    app = FastAPI()
    app.include_router(auth.router, prefix="/api")

    def probe(dependency):
        async def endpoint(actor=Depends(dependency)):
            return {"role": actor["role"], "workspace_id": actor["workspace_id"]}

        return endpoint

    app.get("/authority/can_admin")(probe(auth_deps.require_can_admin))
    app.get("/authority/can_edit")(probe(auth_deps.require_can_edit))

    def database():
        with Session(engine) as current:
            yield current

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    rate_limit._store.clear()
    state = {
        "db": db,
        "client": client,
        "user_id": user_id,
        "ws_id": workspace_id,
        "email": email,
    }
    try:
        yield state
    finally:
        client.close()
        db.rollback()
        db.query(Subscription).filter(Subscription.workspace_id == workspace_id).delete(
            synchronize_session=False
        )
        db.query(AuditEvent).filter(
            or_(AuditEvent.user_id == user_id, AuditEvent.workspace_id == workspace_id)
        ).delete(synchronize_session=False)
        for model in (MfaRecoveryCode, MfaLoginToken, UserMfa, UserSession, UserOAuthAccount):
            db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).delete(
            synchronize_session=False
        )
        db.query(Workspace).filter(Workspace.id == workspace_id).delete(synchronize_session=False)
        db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        db.commit()
        assert counts(db) == before
        rate_limit._store.clear()
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def _cookie_values(response, name: str) -> list[str]:
    values: list[str] = []
    headers = response.headers
    raw_headers = headers.get_list("set-cookie") if hasattr(headers, "get_list") else []
    if not raw_headers:
        single = headers.get("set-cookie")
        raw_headers = [single] if single else []
    for header in raw_headers:
        jar = SimpleCookie()
        jar.load(header)
        morsel = jar.get(name)
        if morsel is not None and morsel.value:
            values.append(morsel.value)
    return values


def session_payload(response):
    values = _cookie_values(response, "tc_session")
    if not values:
        return None
    payload = verify_token(values[-1])
    assert payload is not None
    return payload


def _callback_target(client: TestClient, provider: str) -> tuple[str, str]:
    client.cookies.clear()
    if provider in ("google", "github"):
        return f"/api/auth/oauth/{provider}/callback", _oauth_create_signed_state(provider)
    state = secrets.token_urlsafe(16)
    if provider == "microsoft":
        client.cookies.set("oauth_state", f"{state}|microsoft")
        return "/api/auth/oauth/microsoft/callback", state
    if provider == "oidc":
        client.cookies.set("sso_state", state)
        return "/api/auth/sso/callback", state
    client.cookies.set("idme_state", state)
    return "/api/auth/idme/callback", state


def _callback(client: TestClient, provider: str, *, email: str):
    info = {
        "provider_user_id": f"{provider}-{secrets.token_hex(8)}",
        "email": email,
        "name": "Synthetic Person",
        "email_verified": True,
    }

    async def _exchange(*_args, **_kwargs):
        return info

    async def _discover(*_args, **_kwargs):
        return {
            "authorization_endpoint": "https://idp.example.test/authorize",
            "token_endpoint": "https://idp.example.test/token",
            "userinfo_endpoint": "https://idp.example.test/userinfo",
        }

    targets = {
        "google": "app.api.routes.auth.google_exchange_code",
        "github": "app.api.routes.auth.github_exchange_code",
        "microsoft": "app.api.routes.auth.microsoft_exchange_code",
        "oidc": "app.api.routes.auth.oidc_exchange_code",
        "idme": "app.api.routes.auth.idme_exchange_code",
    }
    path, state = _callback_target(client, provider)
    with ExitStack() as stack:
        stack.enter_context(patch(targets[provider], _exchange))
        if provider == "oidc":
            stack.enter_context(patch("app.api.routes.auth.oidc_discover", _discover))
        return client.get(
            path,
            params={"code": "synthetic-code", "state": state},
            follow_redirects=False,
        )


def sign_in(state, path: str):
    rate_limit._store.clear()
    client = state["client"]
    client.cookies.clear()
    if path == "password":
        return client.post(
            "/api/auth/login",
            json={"email": state["email"], "password": PASSWORD, "remember_me": False},
        )
    return _callback(client, path, email=state["email"])


def plant(state, kind: str, *, required: bool) -> str | None:
    db = state["db"]
    workspace = db.get(Workspace, state["ws_id"])
    workspace.mfa_required = required
    secret = None
    if kind == "enabled":
        secret = generate_totp_secret()
        db.add(
            UserMfa(
                user_id=state["user_id"],
                enabled=True,
                totp_secret_encrypted=encrypt_totp_secret(secret),
            )
        )
    elif kind == "disabled":
        secret = generate_totp_secret()
        db.add(
            UserMfa(
                user_id=state["user_id"],
                enabled=False,
                totp_secret_encrypted=encrypt_totp_secret(secret),
            )
        )
    elif kind == "reenrol":
        secret = generate_totp_secret()
        db.add(
            UserMfa(
                user_id=state["user_id"],
                enabled=False,
                totp_secret_encrypted=encrypt_totp_secret(secret, reenrol_pending=True),
            )
        )
    elif kind == "reset":
        db.add(
            UserMfa(
                user_id=state["user_id"],
                enabled=True,
                totp_secret_encrypted=f"reenrol.{secrets.token_hex(8)}",
            )
        )
    elif kind != "absent":
        raise AssertionError(kind)
    db.commit()
    return secret


def session_rows(state) -> int:
    state["db"].expire_all()
    return state["db"].query(UserSession).filter(UserSession.user_id == state["user_id"]).count()


def challenge_token(response, path: str) -> str:
    assert session_payload(response) is None
    if path == "password":
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["requires_mfa"] is True
        assert "mfa_token" in body
        return body["mfa_token"]
    assert response.status_code == 302, response.text
    parsed = urlsplit(response.headers["location"])
    assert parsed.path == "/login"
    query = parse_qs(parsed.query)
    assert query.get("mfa_token")
    assert "mfa_enrol" not in query
    return query["mfa_token"][0]


def assert_full_access(state, response, path: str) -> None:
    if path == "password":
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("requires_mfa") is not True
        assert body.get("requires_mfa_enrol") is not True
        assert body["workspace_id"] == state["ws_id"]
    else:
        assert response.status_code == 302, response.text
        assert urlsplit(response.headers["location"]).path == "/dashboard"
    payload = session_payload(response)
    assert payload["role"] == "admin"
    assert payload.get("mfa_enrol_only") is not True
    assert payload["workspace_id"] == state["ws_id"]
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200, info.text
    assert info.json()["role"] == "admin"
    assert info.json()["permissions"] == ADMIN_PERMS
    assert state["client"].get("/authority/can_admin").status_code == 200


def assert_enrol_only(state, response, path: str) -> None:
    if path == "password":
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["requires_mfa_enrol"] is True
        assert "mfa_token" not in body
    else:
        assert response.status_code == 302, response.text
        parsed = urlsplit(response.headers["location"])
        assert parsed.path == "/login"
        query = parse_qs(parsed.query)
        assert query.get("mfa_enrol") == ["1"]
        assert "mfa_token" not in query
    payload = session_payload(response)
    assert payload["role"] == "mfa_enrol"
    assert payload.get("mfa_enrol_only") is True
    assert payload["workspace_id"] == state["ws_id"]
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200, info.text
    assert info.json()["role"] == "mfa_enrol"
    assert info.json()["permissions"] == ZERO_PERMS
    assert state["client"].get("/authority/can_admin").status_code in (401, 403)
    assert state["client"].get("/authority/can_edit").status_code in (401, 403)


def complete_code(state, token: str, code: str) -> None:
    response = state["client"].post(
        "/api/auth/mfa/verify-login",
        json={"mfa_token": token, "code": code, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    assert_full_access(state, response, "password")


@pytest.mark.parametrize("path", PATHS)
def test_enabled_factor_withholds_privileged_session_until_totp(enroll_state, path):
    state = enroll_state
    secret = plant(state, "enabled", required=False)
    assert session_rows(state) == 0
    response = sign_in(state, path)
    assert session_rows(state) == 0
    token = challenge_token(response, path)
    assert state["client"].get("/api/auth/me").status_code == 401
    complete_code(state, token, pyotp.TOTP(secret).now())


def test_provider_recovery_code_completes_the_same_challenge(enroll_state):
    state = enroll_state
    plant(state, "enabled", required=False)
    code = "ABCD-EF12"
    state["db"].add(MfaRecoveryCode(user_id=state["user_id"], code_hash=_recovery_code_hash(code)))
    state["db"].commit()
    response = sign_in(state, "google")
    token = challenge_token(response, "google")
    assert session_rows(state) == 0
    complete_code(state, token, code)
    state["db"].expire_all()
    used = state["db"].query(MfaRecoveryCode).filter_by(user_id=state["user_id"]).one()
    assert used.used_at is not None


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("kind", ("absent", "disabled"))
def test_mfa_required_without_enabled_factor_is_enrol_only(enroll_state, path, kind):
    state = enroll_state
    plant(state, kind, required=True)
    response = sign_in(state, path)
    assert_enrol_only(state, response, path)


@pytest.mark.parametrize("path", ("password", "google"))
def test_policy_enrolment_confirm_replaces_the_zero_permission_session(enroll_state, path):
    state = enroll_state
    plant(state, "absent", required=True)
    response = sign_in(state, path)
    assert_enrol_only(state, response, path)
    setup = state["client"].post("/api/auth/mfa/setup")
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    confirmed = state["client"].post(
        "/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert len(set(confirmed.json()["recovery_codes"])) == 10
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200, info.text
    assert info.json()["role"] == "admin"
    assert info.json()["permissions"] == ADMIN_PERMS
    assert state["client"].get("/authority/can_admin").status_code == 200


@pytest.mark.parametrize("path", PATHS)
def test_no_mfa_and_no_requirement_keeps_the_full_session(enroll_state, path):
    state = enroll_state
    plant(state, "absent", required=False)
    assert_full_access(state, sign_in(state, path), path)


@pytest.mark.parametrize("path", ("password", "github"))
def test_disabled_factor_without_requirement_keeps_the_full_session(enroll_state, path):
    state = enroll_state
    plant(state, "disabled", required=False)
    assert_full_access(state, sign_in(state, path), path)


def test_enabled_factor_wins_when_the_workspace_also_requires_mfa(enroll_state):
    state = enroll_state
    secret = plant(state, "enabled", required=True)
    response = sign_in(state, "microsoft")
    assert session_rows(state) == 0
    token = challenge_token(response, "microsoft")
    complete_code(state, token, pyotp.TOTP(secret).now())


def test_provider_reenrol_pending_is_enrol_only(enroll_state):
    state = enroll_state
    plant(state, "reenrol", required=False)
    assert_enrol_only(state, sign_in(state, "idme"), "idme")


def test_provider_reset_marker_issues_no_session(enroll_state):
    state = enroll_state
    plant(state, "reset", required=False)
    response = sign_in(state, "oidc")
    assert response.status_code == 302, response.text
    parsed = urlsplit(response.headers["location"])
    assert parsed.path == "/login"
    assert parse_qs(parsed.query).get("error") == ["mfa_reset_required"]
    assert session_payload(response) is None
    assert session_rows(state) == 0
    assert state["client"].get("/api/auth/me").status_code == 401
