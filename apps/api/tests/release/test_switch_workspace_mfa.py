"""Switching workspaces must enforce the target workspace MFA policy.

Login only applies ``mfa_required`` to the lowest-id membership. These tests
cover the switch: no enabled factor yields the enrol-only session, an enabled
factor without a challenge-satisfied session does not receive the target role,
a challenge-satisfied session may switch, and a target that does not require
MFA is unchanged.

SQLite is the local control. The same cases run on migrated PostgreSQL.
"""

from __future__ import annotations

import secrets
import time
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
    UserSession,
    Workspace,
    WorkspaceMember,
)

pytestmark = pytest.mark.integration

PASSWORD = secrets.token_urlsafe(24)
ZERO = {"can_edit": False, "can_review": False, "can_admin": False, "can_export": False}
MODELS = (
    User,
    Workspace,
    WorkspaceMember,
    UserSession,
    UserMfa,
    MfaRecoveryCode,
    MfaLoginToken,
    AuditEvent,
    Subscription,
)


def counts(db: Session) -> dict[str, int]:
    return {
        model.__tablename__: int(db.scalar(select(func.count()).select_from(model)) or 0)
        for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def switch_state(request):
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
    source = Workspace(name=f"Open {suffix}", slug=f"open-{suffix}", mfa_required=False)
    required = Workspace(name=f"Required {suffix}", slug=f"req-{suffix}", mfa_required=True)
    optional = Workspace(name=f"Optional {suffix}", slug=f"opt-{suffix}", mfa_required=False)
    user = User(
        email=f"switch-mfa-{suffix}@example.test",
        password_hash=hash_password(PASSWORD),
        email_verified=True,
    )
    db.add_all([source, required, optional, user])
    db.flush()
    db.add_all(
        [
            WorkspaceMember(workspace_id=source.id, user_id=user.id, role="reviewer"),
            WorkspaceMember(workspace_id=required.id, user_id=user.id, role="admin"),
            WorkspaceMember(workspace_id=optional.id, user_id=user.id, role="editor"),
        ]
    )
    db.commit()
    ids = {
        "user": user.id,
        "source": source.id,
        "required": required.id,
        "optional": optional.id,
        "email": user.email,
    }
    assert ids["source"] < ids["required"] < ids["optional"]
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
    state = {"db": db, "client": client, **ids}
    try:
        yield state
    finally:
        client.close()
        db.rollback()
        workspace_ids = [ids["source"], ids["required"], ids["optional"]]
        db.query(AuditEvent).filter(
            or_(AuditEvent.user_id == ids["user"], AuditEvent.workspace_id.in_(workspace_ids))
        ).delete(synchronize_session=False)
        db.query(MfaLoginToken).filter(MfaLoginToken.user_id == ids["user"]).delete(
            synchronize_session=False
        )
        for model in (MfaRecoveryCode, UserMfa, UserSession):
            db.query(model).filter(model.user_id == ids["user"]).delete(synchronize_session=False)
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id == ids["user"]).delete(
            synchronize_session=False
        )
        db.query(Workspace).filter(Workspace.id.in_(workspace_ids)).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == ids["user"]).delete(synchronize_session=False)
        db.commit()
        assert counts(db) == before
        rate_limit._store.clear()
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def session_payload(response):
    headers = response.headers
    raw_headers = headers.get_list("set-cookie") if hasattr(headers, "get_list") else []
    if not raw_headers:
        single = headers.get("set-cookie")
        raw_headers = [single] if single else []
    values = []
    for header in raw_headers:
        jar = SimpleCookie()
        jar.load(header)
        morsel = jar.get("tc_session")
        if morsel is not None and morsel.value:
            values.append(morsel)
    if not values:
        return None, None
    morsel = values[-1]
    payload = verify_token(morsel.value)
    assert payload is not None
    return payload, morsel


def login(state) -> dict:
    response = state["client"].post(
        "/api/auth/login",
        json={"email": state["email"], "password": PASSWORD, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    return response.json()


def enable_factor(state) -> str:
    secret = generate_totp_secret()
    state["db"].add(
        UserMfa(
            user_id=state["user"],
            enabled=True,
            totp_secret_encrypted=encrypt_totp_secret(secret),
        )
    )
    state["db"].commit()
    return secret


def session_row(state) -> UserSession:
    """The session the browser cookie currently names. Older rows may remain."""
    raw = state["client"].cookies.get("tc_session")
    assert raw
    payload = verify_token(raw.strip('"'))
    assert payload is not None
    state["db"].expire_all()
    return (
        state["db"]
        .query(UserSession)
        .filter(
            UserSession.user_id == state["user"],
            UserSession.session_id == payload["session_id"],
        )
        .one()
    )


def mfa_satisfied(row: UserSession) -> bool:
    """False when the column is absent, so the unfixed session fails closed in assertions."""
    return bool(getattr(row, "mfa_satisfied", False))


def test_switch_into_required_workspace_without_factor_is_enrol_only(switch_state):
    state = switch_state
    body = login(state)
    assert body.get("requires_mfa") is not True
    assert body.get("requires_mfa_enrol") is not True
    response = state["client"].post(
        "/api/auth/switch-workspace", json={"workspace_id": state["required"]}
    )
    assert response.status_code == 200, response.text
    switched = response.json()
    assert switched["requires_mfa_enrol"] is True
    assert switched.get("requires_mfa") is not True
    assert switched["role"] == "mfa_enrol"
    assert switched["workspace_id"] == state["required"]
    assert switched["mfa_required_for_workspace"] is True
    payload, cookie = session_payload(response)
    assert payload["role"] == "mfa_enrol"
    assert payload.get("mfa_enrol_only") is True
    assert payload["cookie_persistent"] is False
    assert payload["workspace_id"] == state["required"]
    assert cookie["max-age"] == ""
    remaining = payload["exp"] - time.time()
    assert 0 < remaining <= 300
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200, info.text
    assert info.json()["role"] == "mfa_enrol"
    assert info.json()["permissions"] == ZERO
    assert info.json()["mfa_required_for_workspace"] is True
    assert state["client"].get("/authority/can_admin").status_code in (401, 403)
    assert state["client"].get("/authority/can_edit").status_code in (401, 403)
    started = state["client"].post("/api/auth/mfa/setup")
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = state["client"].post(
        "/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirmed.status_code == 200, confirmed.text
    home = state["client"].get("/api/auth/me")
    assert home.status_code == 200, home.text
    assert home.json()["role"] == "admin"
    assert home.json()["workspace_id"] == state["required"]
    assert state["client"].get("/authority/can_admin").status_code == 200
    assert mfa_satisfied(session_row(state)) is True


def test_factor_without_satisfied_session_does_not_grant_target_role(switch_state):
    state = switch_state
    login(state)
    started = state["client"].post("/api/auth/mfa/setup")
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = state["client"].post(
        "/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert mfa_satisfied(session_row(state)) is False
    before = verify_token(state["client"].cookies.get("tc_session").strip('"'))
    response = state["client"].post(
        "/api/auth/switch-workspace", json={"workspace_id": state["required"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requires_mfa"] is True
    assert isinstance(body["mfa_token"], str) and body["mfa_token"]
    assert body.get("role") != "admin"
    assert "set-cookie" not in response.headers
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200, info.text
    assert info.json()["workspace_id"] == state["source"]
    assert info.json()["role"] == "reviewer"
    assert state["client"].get("/authority/can_admin").status_code == 403
    after = verify_token(state["client"].cookies.get("tc_session").strip('"'))
    assert after["workspace_id"] == before["workspace_id"] == state["source"]
    assert after["role"] == "reviewer"
    state["db"].expire_all()
    token = state["db"].query(MfaLoginToken).filter(MfaLoginToken.user_id == state["user"]).one()
    assert token.workspace_id == state["required"]
    assert token.role == "admin"


def test_fresh_challenge_records_satisfaction_and_grants_target_role(switch_state):
    state = switch_state
    login(state)
    secret = enable_factor(state)
    response = state["client"].post(
        "/api/auth/switch-workspace", json={"workspace_id": state["required"]}
    )
    assert response.status_code == 200, response.text
    token = response.json()["mfa_token"]
    completed = state["client"].post(
        "/api/auth/mfa/verify-login",
        json={"mfa_token": token, "code": pyotp.TOTP(secret).now(), "remember_me": False},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json().get("requires_mfa") is not True
    payload, _cookie = session_payload(completed)
    assert payload["workspace_id"] == state["required"]
    assert payload["role"] == "admin"
    assert payload.get("mfa_enrol_only") is not True
    info = state["client"].get("/api/auth/me")
    assert info.json()["role"] == "admin"
    assert info.json()["workspace_id"] == state["required"]
    assert state["client"].get("/authority/can_admin").status_code == 200
    assert mfa_satisfied(session_row(state)) is True


def test_satisfied_session_switches_into_required_workspace(switch_state):
    state = switch_state
    secret = enable_factor(state)
    challenged = login(state)
    assert challenged["requires_mfa"] is True
    completed = state["client"].post(
        "/api/auth/mfa/verify-login",
        json={
            "mfa_token": challenged["mfa_token"],
            "code": pyotp.TOTP(secret).now(),
            "remember_me": False,
        },
    )
    assert completed.status_code == 200, completed.text
    response = state["client"].post(
        "/api/auth/switch-workspace", json={"workspace_id": state["required"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("requires_mfa") is not True
    assert body.get("requires_mfa_enrol") is not True
    assert body["role"] == "admin"
    assert body["workspace_id"] == state["required"]
    payload, _cookie = session_payload(response)
    assert payload["role"] == "admin"
    assert payload.get("mfa_enrol_only") is not True
    assert payload["workspace_id"] == state["required"]
    assert state["client"].get("/authority/can_admin").status_code == 200
    info = state["client"].get("/api/auth/me")
    assert info.json()["role"] == "admin"
    assert info.json()["permissions"]["can_admin"] is True
    assert mfa_satisfied(session_row(state)) is True


def test_target_without_mfa_requirement_still_grants_its_role(switch_state):
    state = switch_state
    login(state)
    response = state["client"].post(
        "/api/auth/switch-workspace", json={"workspace_id": state["optional"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("requires_mfa") is not True
    assert body.get("requires_mfa_enrol") is not True
    assert body["role"] == "editor"
    assert body["workspace_id"] == state["optional"]
    assert body["mfa_required_for_workspace"] is False
    payload, _cookie = session_payload(response)
    assert payload["role"] == "editor"
    assert payload["workspace_id"] == state["optional"]
    assert payload.get("mfa_enrol_only") is not True
    assert state["client"].get("/authority/can_edit").status_code == 200
    assert state["client"].get("/authority/can_admin").status_code == 403


def test_unsatisfied_factor_still_switches_when_target_does_not_require_mfa(switch_state):
    state = switch_state
    login(state)
    enable_factor(state)
    assert mfa_satisfied(session_row(state)) is False
    response = state["client"].post(
        "/api/auth/switch-workspace", json={"workspace_id": state["optional"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("requires_mfa") is not True
    assert body["role"] == "editor"
    assert body["workspace_id"] == state["optional"]
    assert state["client"].get("/authority/can_edit").status_code == 200
    assert state["client"].get("/authority/can_admin").status_code == 403
