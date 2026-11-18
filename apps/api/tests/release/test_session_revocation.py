"""TC-04-005 release test: demotion, removal, and suspension on the next request.

The signed cookie role is the string ``stale``, which is not a membership role.
A passing run therefore cannot be the cookie value leaking through. These cases
drive the member and switch routes. They do not rename ``test_principal_contract``.
"""

import hashlib
import secrets
from datetime import datetime
from http.cookies import SimpleCookie

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes import auth, members
from app.core import auth_deps
from app.core.database import get_db
from app.core.roles import BUILTIN_PERMISSIONS
from app.core.session import sign_session, verify_token
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    Subscription,
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
    AuditEvent,
    ApiKey,
    Subscription,
    CustomRole,
)
SIGNED_ROLE = "stale"
HOME_ROLE = "admin"
OTHER_ROLE = "editor"
DEMOTED_ROLE = "reviewer"
SUSPENDED_DETAIL = "Your account has been suspended in this workspace"
REMOVED_DETAIL = "Active workspace membership required"
SWITCH_DENIED = "Not a member of this workspace"


def counts(db):
    return {
        model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in MODELS
    }


def _use(state, token):
    state["client"].cookies.clear()
    state["client"].cookies.set(auth_deps.SESSION_COOKIE, token)


def _member_id(state):
    _use(state, state["admin_token"])
    listed = state["client"].get("/api/members")
    assert listed.status_code == 200, listed.text
    rows = [row for row in listed.json()["members"] if row["user_id"] == state["target_id"]]
    assert len(rows) == 1
    return rows[0]["id"]


def _membership(state, workspace_id):
    state["db"].expire_all()
    return (
        state["db"]
        .query(WorkspaceMember)
        .filter_by(user_id=state["target_id"], workspace_id=workspace_id)
        .one()
    )


def _switch(state, workspace_id, token=None):
    _use(state, state["target_token"] if token is None else token)
    return state["client"].post("/api/auth/switch-workspace", json={"workspace_id": workspace_id})


def _issued_cookie(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    value = cookie["tc_session"].value
    assert value
    return value


def _enter_other_workspace(state):
    """Switch while the cookie's current membership is still active."""
    moved = _switch(state, state["ws"][1])
    assert moved.status_code == 200, moved.text
    assert moved.json()["workspace_id"] == state["ws"][1]
    assert moved.json()["role"] == OTHER_ROLE
    other_token = _issued_cookie(moved)
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200, info.text
    body = info.json()
    assert body["workspace_id"] == state["ws"][1]
    assert body["role"] == OTHER_ROLE
    assert body["permissions"] == BUILTIN_PERMISSIONS[OTHER_ROLE]
    claims = verify_token(other_token)
    assert claims["role"] == OTHER_ROLE
    assert claims["workspace_id"] == state["ws"][1]
    assert claims["session_id"] == state["target_sid"]
    return other_token


def _me(state):
    _use(state, state["target_token"])
    return state["client"].get("/api/auth/me")


def _probe(state, name, *, token=None, bearer=None):
    if token is None:
        state["client"].cookies.clear()
    else:
        _use(state, token)
    headers = {}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    return state["client"].get(f"/authority/{name}", headers=headers)


def _create_key(state):
    _use(state, state["admin_token"])
    created = state["client"].post(
        "/api/members/api-keys", json={"label": "tc-04-005", "role": "editor"}
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["role"] == "editor"
    assert isinstance(body.get("key"), str) and body["key"]
    return body["id"], body["key"]


def _assert_cookie_and_session_remain(state):
    claims = verify_token(state["target_token"])
    assert claims["role"] == SIGNED_ROLE
    assert claims["workspace_id"] == state["ws"][0]
    assert claims["session_id"] == state["target_sid"]
    state["db"].expire_all()
    row = state["db"].query(UserSession).filter_by(user_id=state["target_id"]).one()
    assert row.session_id == state["target_sid"]


def _assert_other_workspace(state, permissions_role):
    moved = _switch(state, state["ws"][1])
    assert moved.status_code == 200, moved.text
    assert moved.json()["workspace_id"] == state["ws"][1]
    assert moved.json()["role"] == permissions_role
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200, info.text
    body = info.json()
    assert body["workspace_id"] == state["ws"][1]
    assert body["role"] == permissions_role
    assert body["permissions"] == BUILTIN_PERMISSIONS[permissions_role]
    return body


@pytest.fixture(params=("sqlite", "postgres"))
def revocation(request, monkeypatch):
    monkeypatch.setattr(members, "fire_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(members, "notify_user", lambda *args, **kwargs: None)
    monkeypatch.setattr(members, "notify_admins", lambda *args, **kwargs: None)
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        db = request.getfixturevalue("db_session")
        engine = db.get_bind()
        # Seeded workspaces use explicit ids and do not move the sequence.
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
    workspaces = [
        Workspace(name=f"Revocation {suffix}", slug=f"revocation-{suffix}-{i}") for i in (1, 2)
    ]
    users = [
        User(
            email=f"revocation-{suffix}-{i}@example.com",
            password_hash="synthetic-unused",
            email_verified=True,
        )
        for i in (1, 2)
    ]
    db.add_all([*workspaces, *users])
    db.flush()
    workspace_ids = [item.id for item in workspaces]
    user_ids = [item.id for item in users]
    admin_sid = f"revocation-admin-{suffix}"
    target_sid = f"revocation-target-{suffix}"
    created = datetime.utcnow()
    db.add_all(
        [
            WorkspaceMember(workspace_id=workspace_ids[0], user_id=user_ids[0], role=HOME_ROLE),
            WorkspaceMember(workspace_id=workspace_ids[0], user_id=user_ids[1], role=HOME_ROLE),
            WorkspaceMember(workspace_id=workspace_ids[1], user_id=user_ids[1], role=OTHER_ROLE),
            UserSession(user_id=user_ids[0], session_id=admin_sid, created_at=created),
            UserSession(user_id=user_ids[1], session_id=target_sid, created_at=created),
        ]
    )
    db.commit()

    def cookie(user_index, workspace_id, role, session_id):
        return sign_session(
            user_ids[user_index],
            users[user_index].email,
            workspace_id,
            role,
            session_id=session_id,
            max_age_seconds=3600,
        )

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.include_router(members.router, prefix="/api")

    def probe(dependency):
        async def endpoint(actor=Depends(dependency)):
            return {"role": actor["role"], "workspace_id": actor["workspace_id"]}

        return endpoint

    for name in ("can_edit", "can_review", "can_export", "can_admin"):
        app.get(f"/authority/{name}")(probe(getattr(auth_deps, "require_" + name)))

    def database():
        with Session(engine) as current:
            yield current

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    state = {
        "db": db,
        "client": client,
        "ws": workspace_ids,
        "target_id": user_ids[1],
        "target_sid": target_sid,
        "admin_token": cookie(0, workspace_ids[0], HOME_ROLE, admin_sid),
        "target_token": cookie(1, workspace_ids[0], SIGNED_ROLE, target_sid),
    }
    try:
        yield state
    finally:
        client.close()
        db.rollback()
        db.query(AuditEvent).filter(
            or_(AuditEvent.user_id.in_(user_ids), AuditEvent.workspace_id.in_(workspace_ids))
        ).delete(synchronize_session=False)
        db.query(ApiKey).filter(ApiKey.workspace_id.in_(workspace_ids)).delete(
            synchronize_session=False
        )
        db.query(CustomRole).filter(CustomRole.workspace_id.in_(workspace_ids)).delete(
            synchronize_session=False
        )
        for model in (UserMfa, UserSession):
            db.query(model).filter(model.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )
        db.query(Workspace).filter(Workspace.id.in_(workspace_ids)).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
        assert counts(db) == before
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def test_demotion_applies_on_the_existing_cookie_and_other_workspace(revocation):
    state = revocation
    home = _membership(state, state["ws"][0])
    other = _membership(state, state["ws"][1])
    assert home.role == HOME_ROLE and not home.suspended
    assert other.role == OTHER_ROLE and not other.suspended
    member_id = _member_id(state)
    changed = state["client"].patch(f"/api/members/{member_id}", json={"role": DEMOTED_ROLE})
    assert changed.status_code == 200, changed.text
    assert changed.json()["role"] == DEMOTED_ROLE
    info = _me(state)
    assert info.status_code == 200, info.text
    body = info.json()
    assert body["workspace_id"] == state["ws"][0]
    assert body["role"] == DEMOTED_ROLE
    assert body["permissions"] == BUILTIN_PERMISSIONS[DEMOTED_ROLE]
    assert _probe(state, "can_admin", token=state["target_token"]).status_code == 403
    assert _probe(state, "can_review", token=state["target_token"]).status_code == 200
    stayed = _switch(state, state["ws"][0])
    assert stayed.status_code == 200, stayed.text
    assert stayed.json()["role"] == DEMOTED_ROLE
    moved = _assert_other_workspace(state, OTHER_ROLE)
    roles = {item["id"]: item["role"] for item in moved["workspaces"]}
    assert roles == {state["ws"][0]: DEMOTED_ROLE, state["ws"][1]: OTHER_ROLE}
    assert _membership(state, state["ws"][0]).role == DEMOTED_ROLE
    assert _membership(state, state["ws"][1]).role == OTHER_ROLE
    _assert_cookie_and_session_remain(state)


def test_suspension_denies_the_existing_cookie_and_blocks_switch_back(revocation):
    state = revocation
    other_token = _enter_other_workspace(state)
    member_id = _member_id(state)
    suspended = state["client"].patch(f"/api/members/{member_id}/suspend", json={"suspended": True})
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["suspended"] is True
    info = _me(state)
    assert info.status_code == 403
    assert info.json()["detail"] == SUSPENDED_DETAIL
    # require_session reads the cookie's current workspace before the target.
    denied = _switch(state, state["ws"][1])
    assert denied.status_code == 403
    assert denied.json()["detail"] == SUSPENDED_DETAIL
    assert "set-cookie" not in denied.headers
    _use(state, other_token)
    kept = state["client"].get("/api/auth/me")
    assert kept.status_code == 200, kept.text
    body = kept.json()
    assert body["workspace_id"] == state["ws"][1]
    assert body["role"] == OTHER_ROLE
    assert body["permissions"] == BUILTIN_PERMISSIONS[OTHER_ROLE]
    roles = {item["id"]: item["role"] for item in body["workspaces"]}
    assert roles[state["ws"][0]] == HOME_ROLE
    assert roles[state["ws"][1]] == OTHER_ROLE
    back = _switch(state, state["ws"][0], other_token)
    assert back.status_code == 403
    assert back.json()["detail"] == SWITCH_DENIED
    assert "set-cookie" not in back.headers
    still = state["client"].get("/api/auth/me")
    assert still.status_code == 200, still.text
    assert still.json()["workspace_id"] == state["ws"][1]
    assert still.json()["permissions"] == BUILTIN_PERMISSIONS[OTHER_ROLE]
    home = _membership(state, state["ws"][0])
    assert home.role == HOME_ROLE and home.suspended
    assert _membership(state, state["ws"][1]).role == OTHER_ROLE
    assert not _membership(state, state["ws"][1]).suspended
    _assert_cookie_and_session_remain(state)


def test_removal_denies_that_workspace_and_keeps_only_the_other(revocation):
    state = revocation
    other_token = _enter_other_workspace(state)
    key_id, raw = _create_key(state)
    removed = state["client"].delete(f"/api/members/{_member_id(state)}")
    assert removed.status_code == 200, removed.text
    info = _me(state)
    assert info.status_code == 403
    assert info.json()["detail"] == REMOVED_DETAIL
    denied = _switch(state, state["ws"][1])
    assert denied.status_code == 403
    assert denied.json()["detail"] == REMOVED_DETAIL
    assert "set-cookie" not in denied.headers
    _use(state, other_token)
    kept = state["client"].get("/api/auth/me")
    assert kept.status_code == 200, kept.text
    body = kept.json()
    assert body["workspace_id"] == state["ws"][1]
    assert body["role"] == OTHER_ROLE
    assert body["permissions"] == BUILTIN_PERMISSIONS[OTHER_ROLE]
    assert [item["id"] for item in body["workspaces"]] == [state["ws"][1]]
    assert body["workspaces"][0]["role"] == OTHER_ROLE
    back = _switch(state, state["ws"][0], other_token)
    assert back.status_code == 403
    assert back.json()["detail"] == SWITCH_DENIED
    assert "set-cookie" not in back.headers
    still = state["client"].get("/api/auth/me")
    assert still.status_code == 200
    assert still.json()["workspace_id"] == state["ws"][1]
    assert still.json()["permissions"] == BUILTIN_PERMISSIONS[OTHER_ROLE]
    state["db"].expire_all()
    gone = (
        state["db"]
        .query(WorkspaceMember)
        .filter_by(user_id=state["target_id"], workspace_id=state["ws"][0])
        .one_or_none()
    )
    assert gone is None
    assert state["db"].get(User, state["target_id"]) is not None
    assert _membership(state, state["ws"][1]).role == OTHER_ROLE
    _assert_cookie_and_session_remain(state)
    probe = _probe(state, "can_edit", bearer=raw)
    assert probe.status_code == 200
    assert probe.json() == {"role": "editor", "workspace_id": state["ws"][0]}
    state["db"].expire_all()
    assert state["db"].get(ApiKey, key_id) is not None


def test_suspending_a_member_does_not_revoke_workspace_api_keys(revocation):
    state = revocation
    key_id, raw = _create_key(state)
    _use(state, state["admin_token"])
    suspended = state["client"].patch(
        f"/api/members/{_member_id(state)}/suspend", json={"suspended": True}
    )
    assert suspended.status_code == 200, suspended.text
    kept = _probe(state, "can_edit", token=state["target_token"], bearer=raw)
    assert kept.status_code == 200
    assert kept.json() == {"role": "editor", "workspace_id": state["ws"][0]}
    assert _probe(state, "can_admin", bearer=raw).status_code == 403
    human = _probe(state, "can_edit", token=state["target_token"])
    assert human.status_code == 403
    me = _me(state)
    assert me.status_code == 403
    assert me.json()["detail"] == SUSPENDED_DETAIL
    state["db"].expire_all()
    row = state["db"].get(ApiKey, key_id)
    assert row is not None
    assert row.role == "editor"
    assert row.expires_at is None
    assert row.key_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert row.workspace_id == state["ws"][0]


def test_admin_revoke_sessions_invalidates_the_cookie_and_leaves_api_keys(revocation):
    state = revocation
    key_id, raw = _create_key(state)
    _use(state, state["admin_token"])
    response = state["client"].post(f"/api/members/{_member_id(state)}/revoke-sessions")
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert response.json()["revoked"] == 1
    state["db"].expire_all()
    # The row stays. Revoke stamps this workspace only; the same session can
    # still be used where it was not revoked. The cookie for this workspace
    # is rejected below.
    rows = state["db"].query(UserSession).filter_by(user_id=state["target_id"]).all()
    assert [row.session_id for row in rows] == [state["target_sid"]]
    home = _membership(state, state["ws"][0])
    other = _membership(state, state["ws"][1])
    assert home.sessions_revoked_at is not None
    assert other.sessions_revoked_at is None
    admin_sid = verify_token(state["admin_token"])["session_id"]
    assert state["db"].query(UserSession).filter_by(session_id=admin_sid).count() == 1
    assert home.role == HOME_ROLE
    assert other.role == OTHER_ROLE
    info = _me(state)
    assert info.status_code == 401
    assert info.json()["detail"] == "Session invalidated"
    probe = _probe(state, "can_edit", bearer=raw)
    assert probe.status_code == 200
    assert probe.json()["role"] == "editor"
    state["db"].expire_all()
    assert state["db"].get(ApiKey, key_id) is not None
