"""TC-04-005a: an admin revoke must not sign the user out of other workspaces.

``user_sessions`` does not store a workspace. The active workspace is only in the
signed cookie, and ``POST /api/auth/switch-workspace`` re-reads membership before
it reissues that cookie. Deleting every ``UserSession`` for the user therefore
signs them out of workspaces the caller does not administer, and deleting only
the rows "currently" on this workspace cannot be done from the row alone.
"""

import secrets
import time
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

import pytest
from fastapi import FastAPI
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
HOME_ROLE = "admin"
OTHER_ROLE = "editor"
SIGNED_ROLE = "stale"
REVOKED_DETAIL = "Session invalidated"


def _counts(db):
    return {
        model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in MODELS
    }


def _use(state, token):
    state["client"].cookies.clear()
    state["client"].cookies.set(auth_deps.SESSION_COOKIE, token)


def _cookie(user, workspace_id, session_id):
    return sign_session(
        user.id,
        user.email,
        workspace_id,
        SIGNED_ROLE,
        session_id=session_id,
        max_age_seconds=3600,
    )


def _me(state, token):
    _use(state, token)
    return state["client"].get("/api/auth/me")


def _switch(state, token, workspace_id):
    _use(state, token)
    return state["client"].post("/api/auth/switch-workspace", json={"workspace_id": workspace_id})


def _membership(state, user_id, workspace_id):
    state["db"].expire_all()
    return (
        state["db"]
        .query(WorkspaceMember)
        .filter_by(user_id=user_id, workspace_id=workspace_id)
        .one()
    )


def _sessions(state, user_id):
    state["db"].expire_all()
    return state["db"].query(UserSession).filter_by(user_id=user_id).all()


def _naive_utc(value):
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _usable_after(cutoff):
    """A stored timestamp strictly after the cutoff and not in the future."""
    cutoff = _naive_utc(cutoff)
    target = cutoff + timedelta(seconds=2)
    deadline = time.time() + 5
    while datetime.utcnow() < target and time.time() < deadline:
        time.sleep(0.05)
    now = datetime.utcnow()
    assert now >= target
    assert target > cutoff
    return target


def _issued_cookie(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    value = cookie["tc_session"].value
    assert value
    return value


@pytest.fixture(params=("sqlite", "postgres"))
def scoped(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        db = request.getfixturevalue("db_session")
        engine = db.get_bind()
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
            for model in MODELS:
                connection.execute(CreateTable(model.__table__))
        db = Session(engine)
    before = _counts(db)
    suffix = secrets.token_hex(8)
    workspaces = [
        Workspace(name=f"Scope {suffix} {label}", slug=f"scope-{suffix}-{label}")
        for label in ("a", "b")
    ]
    users = [
        User(
            email=f"scope-{suffix}-{name}@example.com",
            password_hash="synthetic-unused",
            email_verified=True,
        )
        for name in ("admin", "target", "stranger")
    ]
    db.add_all([*workspaces, *users])
    db.flush()
    workspace_a, workspace_b = (item.id for item in workspaces)
    admin, target, stranger = users
    created = datetime.utcnow() - timedelta(days=1)
    admin_sid = f"scope-admin-{suffix}"
    target_a_sid = f"scope-target-a-{suffix}"
    target_b_sid = f"scope-target-b-{suffix}"
    stranger_sid = f"scope-stranger-{suffix}"
    db.add_all(
        [
            WorkspaceMember(workspace_id=workspace_a, user_id=admin.id, role=HOME_ROLE),
            WorkspaceMember(workspace_id=workspace_a, user_id=target.id, role=HOME_ROLE),
            WorkspaceMember(workspace_id=workspace_b, user_id=target.id, role=OTHER_ROLE),
            WorkspaceMember(workspace_id=workspace_b, user_id=stranger.id, role=OTHER_ROLE),
            UserSession(user_id=admin.id, session_id=admin_sid, created_at=created),
            UserSession(user_id=target.id, session_id=target_a_sid, created_at=created),
            UserSession(user_id=target.id, session_id=target_b_sid, created_at=created),
            UserSession(user_id=stranger.id, session_id=stranger_sid, created_at=created),
        ]
    )
    db.commit()
    user_ids = [admin.id, target.id, stranger.id]
    workspace_ids = [workspace_a, workspace_b]

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.include_router(members.router, prefix="/api")

    def database():
        with Session(engine) as current:
            yield current

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    state = {
        "db": db,
        "client": client,
        "ws": workspace_ids,
        "admin": admin,
        "target": target,
        "stranger": stranger,
        "admin_sid": admin_sid,
        "target_a_sid": target_a_sid,
        "target_b_sid": target_b_sid,
        "stranger_sid": stranger_sid,
        "admin_token": _cookie(admin, workspace_a, admin_sid),
        "token_a": _cookie(target, workspace_a, target_a_sid),
        "token_b": _cookie(target, workspace_b, target_b_sid),
        "stranger_token": _cookie(stranger, workspace_b, stranger_sid),
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
        assert _counts(db) == before
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def _revoke(state, member_id, token=None):
    _use(state, state["admin_token"] if token is None else token)
    return state["client"].post(f"/api/members/{member_id}/revoke-sessions")


def test_workspace_revoke_leaves_the_other_workspace_session(scoped):
    state = scoped
    workspace_a, workspace_b = state["ws"]
    target = state["target"]
    member_a = _membership(state, target.id, workspace_a)
    before = _me(state, state["token_b"])
    assert before.status_code == 200, before.text
    assert before.json()["workspace_id"] == workspace_b
    assert before.json()["role"] == OTHER_ROLE
    assert before.json()["permissions"] == BUILTIN_PERMISSIONS[OTHER_ROLE]

    revoked = _revoke(state, member_a.id)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["ok"] is True
    assert revoked.json()["revoked"] == 2

    # The session pointed at B must keep working. Master deletes every row for
    # the user, so this is 401 "Session invalidated" before the fix.
    kept = _me(state, state["token_b"])
    assert kept.status_code == 200, kept.text
    body = kept.json()
    assert body["workspace_id"] == workspace_b
    assert body["role"] == OTHER_ROLE
    assert body["permissions"] == BUILTIN_PERMISSIONS[OTHER_ROLE]
    assert verify_token(state["token_b"])["session_id"] == state["target_b_sid"]

    denied = _switch(state, state["token_b"], workspace_a)
    assert denied.status_code == 401
    assert denied.json()["detail"] == REVOKED_DETAIL
    assert "set-cookie" not in denied.headers
    still = _me(state, state["token_b"])
    assert still.status_code == 200, still.text
    assert still.json()["workspace_id"] == workspace_b

    stale_a = _cookie(target, workspace_a, state["target_b_sid"])
    stale = _me(state, stale_a)
    assert stale.status_code == 401
    assert stale.json()["detail"] == REVOKED_DETAIL
    still_b = _me(state, state["token_b"])
    assert still_b.status_code == 200, still_b.text

    pointed_at_a = _me(state, state["token_a"])
    assert pointed_at_a.status_code == 401
    assert pointed_at_a.json()["detail"] == REVOKED_DETAIL
    # The browser stuck on A can leave for B. It cannot read A, and the
    # reissued cookie cannot come back.
    left = _switch(state, state["token_a"], workspace_b)
    assert left.status_code == 200, left.text
    left_cookie = _issued_cookie(left)
    assert verify_token(left_cookie)["session_id"] == state["target_a_sid"]
    assert verify_token(left_cookie)["workspace_id"] == workspace_b
    left_me = _me(state, left_cookie)
    assert left_me.status_code == 200, left_me.text
    assert left_me.json()["workspace_id"] == workspace_b
    assert left_me.json()["role"] == OTHER_ROLE
    come_back = _switch(state, left_cookie, workspace_a)
    assert come_back.status_code == 401
    assert come_back.json()["detail"] == REVOKED_DETAIL
    assert "set-cookie" not in come_back.headers
    stayed = _me(state, left_cookie)
    assert stayed.status_code == 200, stayed.text
    assert stayed.json()["workspace_id"] == workspace_b
    still_blocked = _me(state, state["token_a"])
    assert still_blocked.status_code == 401

    rows = {row.session_id: row for row in _sessions(state, target.id)}
    assert set(rows) == {state["target_a_sid"], state["target_b_sid"]}
    home = _membership(state, target.id, workspace_a)
    other = _membership(state, target.id, workspace_b)
    assert home.role == HOME_ROLE and not home.suspended
    assert other.role == OTHER_ROLE and not other.suspended
    assert home.sessions_revoked_at is not None
    assert other.sessions_revoked_at is None
    rows[state["target_a_sid"]].created_at = home.sessions_revoked_at
    state["db"].commit()
    equal = _me(state, state["token_a"])
    assert equal.status_code == 401
    assert equal.json()["detail"] == REVOKED_DETAIL

    fresh_sid = f"{state['target_b_sid']}-fresh"
    fresh_created = _usable_after(home.sessions_revoked_at)
    state["db"].add(UserSession(user_id=target.id, session_id=fresh_sid, created_at=fresh_created))
    state["db"].commit()
    fresh = _cookie(target, workspace_a, fresh_sid)
    restored = _me(state, fresh)
    assert restored.status_code == 200, restored.text
    assert restored.json()["workspace_id"] == workspace_a
    assert restored.json()["role"] == HOME_ROLE
    moved = _switch(state, fresh, workspace_b)
    assert moved.status_code == 200, moved.text
    issued = _issued_cookie(moved)
    assert verify_token(issued)["session_id"] == fresh_sid
    assert verify_token(issued)["workspace_id"] == workspace_b
    on_b = _me(state, issued)
    assert on_b.status_code == 200, on_b.text
    assert on_b.json()["workspace_id"] == workspace_b
    back = _switch(state, issued, workspace_a)
    assert back.status_code == 200, back.text
    assert back.json()["workspace_id"] == workspace_a
    assert back.json()["role"] == HOME_ROLE

    admin_me = _me(state, state["admin_token"])
    assert admin_me.status_code == 200, admin_me.text
    assert admin_me.json()["workspace_id"] == workspace_a
    assert len(_sessions(state, state["admin"].id)) == 1
    wrong = _revoke(state, other.id)
    assert wrong.status_code == 404
    assert _membership(state, target.id, workspace_b).sessions_revoked_at is None
    assert len(_sessions(state, target.id)) == 3


def test_revoke_sessions_rejects_a_member_outside_the_caller_workspace(scoped):
    state = scoped
    stranger = state["stranger"]
    stranger_member = _membership(state, stranger.id, state["ws"][1])
    denied = _revoke(state, stranger_member.id)
    assert denied.status_code == 404
    assert denied.json()["detail"] == "Member not found"
    kept = _me(state, state["stranger_token"])
    assert kept.status_code == 200, kept.text
    assert kept.json()["workspace_id"] == state["ws"][1]
    assert kept.json()["role"] == OTHER_ROLE
    assert [row.session_id for row in _sessions(state, stranger.id)] == [state["stranger_sid"]]
    assert sorted(row.session_id for row in _sessions(state, state["target"].id)) == sorted(
        (state["target_a_sid"], state["target_b_sid"])
    )
    home = _membership(state, state["target"].id, state["ws"][0])
    assert home.sessions_revoked_at is None


def test_self_service_revoke_all_still_deletes_every_session(scoped):
    state = scoped
    target = state["target"]
    _use(state, state["token_b"])
    revoked = state["client"].post("/api/auth/sessions/revoke-all")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["ok"] is True
    assert revoked.json()["revoked"] == 2
    assert _sessions(state, target.id) == []
    for token in (state["token_a"], state["token_b"]):
        denied = _me(state, token)
        assert denied.status_code == 401
        assert denied.json()["detail"] == REVOKED_DETAIL
    assert len(_sessions(state, state["admin"].id)) == 1
    assert _membership(state, target.id, state["ws"][0]).sessions_revoked_at is None
    assert _membership(state, target.id, state["ws"][1]).sessions_revoked_at is None


def test_member_revocation_migration_is_the_single_head():
    """The cutoff column is a real revision, parented on the previous single head.

    A later revision may be the only head. This one stays on that chain.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_root = Path(__file__).resolve().parents[2]
    script = ScriptDirectory.from_config(Config(str(api_root / "alembic.ini")))
    heads = list(script.get_heads())
    assert len(heads) == 1
    revision = script.get_revision("tc04005a_member_revoked_at")
    assert revision is not None
    assert isinstance(revision.down_revision, str)
    assert revision.down_revision == "tc17005a_share_token"
    assert len(revision.revision) <= 32
    current: str | None = heads[0]
    seen: set[str] = set()
    while current and current not in seen:
        if current == "tc04005a_member_revoked_at":
            break
        seen.add(current)
        down = script.get_revision(current).down_revision
        assert isinstance(down, str)
        current = down
    assert current == "tc04005a_member_revoked_at"
    source = (api_root / "alembic" / "versions" / "tc04005a_member_revoked_at.py").read_text(
        encoding="utf-8"
    )
    assert "sessions_revoked_at" in source
    assert "import app" not in source and "from app" not in source
