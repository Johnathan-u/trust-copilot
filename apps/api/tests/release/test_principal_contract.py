"""Current-membership subset only: real HTTP dependencies/routes, no auth mocks.

SQLite runs provide local regression controls. The same cases run against the
migrated PostgreSQL fixture; SQLite is not PostgreSQL release qualification.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes import auth, members, trust_articles, workspaces
from app.core import auth_deps
from app.core.config import SIGNUP_POLICY_SELF_SIGNUP, get_settings
from app.core.database import get_db
from app.core.mfa import encrypt_totp_secret, generate_totp_secret
from app.core.session import sign_session, verify_token
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    MfaLoginToken,
    MfaRecoveryCode,
    Subscription,
    TrustArticle,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)

MODELS = (
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
    TrustArticle,
)
PERMISSIONS = {
    "admin": (True, True, True, True),
    "editor": (True, True, True, False),
    "reviewer": (False, True, False, False),
    "custom": (False, True, True, False),
    "unconfigured": (False, False, False, False),
}
NAMES = ("can_edit", "can_review", "can_export", "can_admin")


def counts(db):
    return {
        model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def authority(request, monkeypatch):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        db = request.getfixturevalue("db_session")
        engine = db.get_bind()
        # The common fixture seeds workspaces 1..3 with explicit ids. Match the
        # existing onboarding fixture's sequence setup, without moving it back,
        # so real POST /workspaces can allocate an id on a fresh migrated DB.
        db.execute(
            text("""
            SELECT setval(pg_get_serial_sequence('workspaces', 'id'), GREATEST(
                (SELECT COALESCE(MAX(id), 1) FROM workspaces),
                (SELECT last_value FROM workspaces_id_seq)
            ))
        """)
        )
        db.commit()
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            for model in MODELS:
                connection.execute(CreateTable(model.__table__))
        db = Session(engine)
    before = counts(db)
    suffix = secrets.token_hex(8)
    ws = [Workspace(name=f"Authority {suffix}", slug=f"authority-{suffix}-{i}") for i in (1, 2)]
    users = [
        User(
            email=f"authority-{suffix}-{i}@example.com",
            password_hash="synthetic-unused",
            email_verified=True,
        )
        for i in (1, 2)
    ]
    db.add_all([*ws, *users])
    db.flush()
    ws_ids, user_ids = [item.id for item in ws], [item.id for item in users]
    actor = WorkspaceMember(workspace_id=ws_ids[0], user_id=user_ids[0], role="admin")
    sid = f"authority-{suffix}"
    db.add_all(
        [
            actor,
            UserSession(user_id=user_ids[0], session_id=sid),
            UserSession(user_id=user_ids[1], session_id=sid + "-pending"),
            CustomRole(workspace_id=ws_ids[0], name="custom", can_review=True, can_export=True),
            TrustArticle(
                workspace_id=ws_ids[0],
                slug=f"private-{suffix}",
                title="Private authority article",
                published=0,
            ),
            TrustArticle(
                workspace_id=ws_ids[0],
                slug=f"public-{suffix}",
                title="Public authority article",
                published=1,
            ),
        ]
    )
    db.commit()
    private_id = db.query(TrustArticle.id).filter_by(slug=f"private-{suffix}").scalar()
    public_id = db.query(TrustArticle.id).filter_by(slug=f"public-{suffix}").scalar()
    app = FastAPI()
    for router in (auth.router, members.router, trust_articles.router, workspaces.router):
        app.include_router(router, prefix="/api")

    # Explicit HTTP probes exercise every existing permission dependency; actual
    # /members/roles, /auth/me and /trust-articles routes are asserted below too.
    def probe(dependency):
        async def endpoint(actor=Depends(dependency)):
            return {"role": actor["role"], "workspace_id": actor["workspace_id"]}

        return endpoint

    app.get("/authority/required")(probe(auth_deps.require_session))
    for name in NAMES:
        app.get(f"/authority/{name}")(probe(getattr(auth_deps, "require_" + name)))

    def database():
        with Session(engine) as current:
            yield current

    app.dependency_overrides[get_db] = database
    client = TestClient(app)

    def cookie(role="admin", *, pending=False, enrol=False):
        index = 1 if pending else 0
        token = sign_session(
            user_ids[index],
            users[index].email,
            0 if pending else ws_ids[0],
            "pending" if pending else role,
            session_id=sid + ("-pending" if pending else ""),
            max_age_seconds=3600,
            mfa_enrol_only=enrol,
        )
        client.cookies.clear()
        client.cookies.set("tc_session", token)
        return token

    state = {
        "db": db,
        "client": client,
        "actor": actor,
        "ws": ws_ids,
        "users": user_ids,
        "private": private_id,
        "public": public_id,
        "cookie": cookie,
        "suffix": suffix,
    }
    cookie()
    try:
        yield state
    finally:
        client.close()
        db.rollback()
        # Workspace creation is covered, so include only this fixture's new slug.
        owned_ws = list(ws_ids) + [
            value
            for (value,) in db.query(Workspace.id).filter(Workspace.slug == f"created-{suffix}")
        ]
        db.query(AuditEvent).filter(
            or_(AuditEvent.user_id.in_(user_ids), AuditEvent.workspace_id.in_(owned_ws))
        ).delete(synchronize_session=False)
        for model in (TrustArticle, Subscription, ApiKey, CustomRole):
            db.query(model).filter(model.workspace_id.in_(owned_ws)).delete(
                synchronize_session=False
            )
        for model in (MfaRecoveryCode, MfaLoginToken, UserMfa, UserSession):
            db.query(model).filter(model.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )
        db.query(Workspace).filter(Workspace.id.in_(owned_ws)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
        assert counts(db) == before
        if request.param == "sqlite":
            db.close()
            engine.dispose()


@pytest.mark.parametrize("role", PERMISSIONS)
def test_cookie_permissions_follow_current_membership(authority, role):
    state = authority
    state["actor"].role = role
    state["db"].commit()
    token = state["cookie"]("admin")
    expected = dict(zip(NAMES, PERMISSIONS[role]))
    for name, allowed in expected.items():
        response = state["client"].get(f"/authority/{name}")
        assert response.status_code == (200 if allowed else 403), (role, name, response.text)
        if allowed:
            assert response.json()["role"] == role
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200
    assert info.json()["role"] == role
    assert info.json()["permissions"] == expected
    assert state["client"].get("/api/members/roles").status_code == (
        200 if expected["can_admin"] else 403
    )
    assert (
        verify_token(token)["role"] == "admin"
    )  # Resolution must not rely on refreshing the cookie.


@pytest.mark.parametrize("change", ("removed", "suspended"))
@pytest.mark.parametrize("entry", ("required", "optional", "me"))
def test_required_optional_and_me_deny_inactive_membership(authority, change, entry):
    state = authority
    if change == "removed":
        state["db"].delete(state["actor"])
    else:
        state["actor"].suspended = True
    state["db"].commit()
    before = counts(state["db"])
    if entry == "required":
        for route in ("/authority/required", "/authority/can_admin", "/api/members/roles"):
            assert state["client"].get(route).status_code == 403
    elif entry == "optional":
        assert state["client"].get("/api/trust-articles").status_code == 401
        assert state["client"].get(f"/api/trust-articles/{state['private']}").status_code == 404
        # Optional authentication must still preserve genuinely public reads.
        assert state["client"].get(f"/api/trust-articles/{state['public']}").status_code == 200
    else:
        assert state["client"].get("/api/auth/me").status_code == 403
    assert counts(state["db"]) == before


def test_anonymous_optional_auth_never_exposes_unpublished_articles(authority):
    state = authority
    state["client"].cookies.clear()
    assert state["client"].get("/authority/required").status_code == 401
    assert state["client"].get(f"/api/trust-articles/{state['private']}").status_code == 404
    assert state["client"].get(f"/api/trust-articles/{state['public']}").status_code == 200


def test_membership_and_custom_permission_changes_apply_on_the_next_request(authority):
    state = authority
    assert state["client"].get("/api/members/roles").status_code == 200
    state["actor"].role = "custom"
    state["db"].commit()
    assert state["client"].get("/api/members/roles").status_code == 403
    assert state["client"].get("/authority/can_export").status_code == 200
    custom = (
        state["db"].query(CustomRole).filter_by(workspace_id=state["ws"][0], name="custom").one()
    )
    custom.can_export = False
    state["db"].commit()
    assert state["client"].get("/authority/can_export").status_code == 403
    assert state["client"].get("/api/auth/me").json()["permissions"]["can_export"] is False


def test_api_key_authentication_preserves_existing_workspace_role_rules(authority):
    state = authority
    raw = secrets.token_urlsafe(24)
    key = ApiKey(
        workspace_id=state["ws"][0],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        role="editor",
    )
    state["db"].add(key)
    state["actor"].suspended = True
    state["db"].commit()
    headers = {"Authorization": f"Bearer {raw}"}
    assert state["client"].get("/authority/can_edit", headers=headers).status_code == 200
    assert state["client"].get("/authority/can_admin", headers=headers).status_code == 403
    # /me stays cookie-only, even with a valid bearer key alongside it.
    assert state["client"].get("/api/auth/me", headers=headers).status_code == 403
    state["client"].cookies.clear()
    key.expires_at = datetime.utcnow() - timedelta(seconds=1)
    state["db"].commit()
    assert state["client"].get("/authority/required", headers=headers).status_code == 401


@pytest.mark.parametrize("target", ("active", "suspended", "missing"))
def test_workspace_switch_uses_current_active_target_membership(authority, target):
    state = authority
    if target != "missing":
        state["db"].add(
            WorkspaceMember(
                workspace_id=state["ws"][1],
                user_id=state["users"][0],
                role="reviewer",
                suspended=target == "suspended",
            )
        )
        state["db"].commit()
    before = counts(state["db"])
    response = state["client"].post(
        "/api/auth/switch-workspace", json={"workspace_id": state["ws"][1]}
    )
    if target == "active":
        assert response.status_code == 200
        assert response.json()["role"] == "reviewer"
        info = state["client"].get("/api/auth/me").json()
        assert info["workspace_id"] == state["ws"][1]
        assert info["role"] == "reviewer"
        assert info["permissions"] == dict(zip(NAMES, PERMISSIONS["reviewer"]))
    else:
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert counts(state["db"]) == before


def test_pending_onboarding_is_account_only_and_can_create_its_first_workspace(
    authority, monkeypatch
):
    state = authority
    state["cookie"](pending=True)
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200
    assert info.json()["needs_onboarding"] is True
    assert not any(info.json()["permissions"].values())
    assert state["client"].get("/api/auth/sessions").status_code == 200
    assert state["client"].get("/authority/required").status_code == 403
    assert state["client"].get(f"/api/trust-articles/{state['private']}").status_code == 404
    monkeypatch.setattr(get_settings(), "signup_policy", SIGNUP_POLICY_SELF_SIGNUP)
    policy = state["client"].get("/api/workspaces/creation-policy")
    assert policy.status_code == 200
    assert policy.json()["can_create_workspace"] is True
    response = state["client"].post("/api/workspaces", json={"name": f"created-{state['suffix']}"})
    assert response.status_code == 200, response.text
    info = state["client"].get("/api/auth/me").json()
    assert info["workspace_id"] == response.json()["id"]
    assert info["role"] == "admin"
    assert not info.get("needs_onboarding", False)


def test_stale_pending_role_does_not_skip_positive_workspace_membership(authority):
    state = authority
    state["cookie"]("pending")
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200
    assert info.json()["workspace_id"] == state["ws"][0]
    assert info.json()["role"] == "admin"
    state["db"].delete(state["actor"])
    state["db"].commit()
    assert state["client"].get("/api/auth/me").status_code == 403


def test_mfa_enrolment_keeps_zero_permissions_and_existing_account_routes(authority):
    state = authority
    state["db"].add(
        UserMfa(
            user_id=state["users"][0],
            enabled=False,
            totp_secret_encrypted=encrypt_totp_secret(generate_totp_secret(), reenrol_pending=True),
        )
    )
    state["db"].commit()
    state["cookie"]("mfa_enrol", enrol=True)
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200
    assert info.json()["role"] == "mfa_enrol"
    assert not any(info.json()["permissions"].values())
    assert state["client"].get("/api/auth/mfa/status").status_code == 200
    assert state["client"].get("/api/auth/sessions").status_code == 200
    assert state["client"].get("/authority/can_admin").status_code in (401, 403)
    assert state["client"].get(f"/api/trust-articles/{state['private']}").status_code == 404
    assert state["client"].post(
        "/api/auth/switch-workspace", json={"workspace_id": state["ws"][1]}
    ).status_code in (401, 403)


@pytest.mark.parametrize("change", ("removed", "suspended"))
def test_mfa_enrolment_does_not_bypass_inactive_membership(authority, change):
    state = authority
    state["db"].add(
        UserMfa(
            user_id=state["users"][0],
            enabled=False,
            totp_secret_encrypted=encrypt_totp_secret(generate_totp_secret(), reenrol_pending=True),
        )
    )
    if change == "removed":
        state["db"].delete(state["actor"])
    else:
        state["actor"].suspended = True
    state["db"].commit()
    state["cookie"]("mfa_enrol", enrol=True)
    assert state["client"].get("/api/auth/me").status_code == 403
    assert state["client"].get("/api/auth/mfa/status").status_code == 403
