"""Custom-role definition grant bounds with real stored human authorization.

SQLite controls are separate from the identical migrated-PostgreSQL cases.
Only the database connection dependency is replaced, never auth or role logic.
"""

import hashlib
import json
import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes import auth, members
from app.core.database import get_db
from app.core.session import sign_session
from app.models import (
    AuditEvent,
    CustomRole,
    Subscription,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)

FLAGS = ("can_edit", "can_review", "can_export", "can_admin")
FALSE_FLAGS = dict.fromkeys(FLAGS, False)
MODELS = (
    User,
    Workspace,
    WorkspaceMember,
    UserSession,
    UserMfa,
    Subscription,
    CustomRole,
    AuditEvent,
)


def snapshot(db):
    return {
        model.__tablename__: hashlib.sha256(
            json.dumps(
                [
                    dict(row)
                    for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
                ],
                default=str,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def grants(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        db = request.getfixturevalue("db_session")
        engine = db.get_bind()
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
    baseline = snapshot(db)
    token = secrets.token_hex(8)
    ws_ids, user_ids, clients = [], [], []
    try:
        for name in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if wid not in ws_ids and db.get(Workspace, wid) is None:
                    break
            db.add(Workspace(id=wid, name=name, slug=f"role-grants-{name}-{token}"))
            db.flush()
            ws_ids.append(wid)
        actors = {}
        for name in ("limited", "admin"):
            user = User(
                email=f"grants-{name}-{token}@example.com", password_hash="synthetic-unused"
            )
            db.add(user)
            db.flush()
            user_ids.append(user.id)
            member = WorkspaceMember(user_id=user.id, workspace_id=ws_ids[0], role=name)
            sid = f"grants-{name}-{token}"
            db.add_all([member, UserSession(user_id=user.id, session_id=sid)])
            db.flush()
            # Deliberately stale admin claim: current membership and current
            # custom flags must determine authority on each real request.
            actors[name] = {
                "member": member,
                "cookie": sign_session(
                    user.id,
                    user.email,
                    ws_ids[0],
                    "admin",
                    session_id=sid,
                    max_age_seconds=3600,
                ),
            }
        definitions = {}
        for name, wid, flags in (
            ("limited", ws_ids[0], {**FALSE_FLAGS, "can_admin": True}),
            ("empty", ws_ids[0], FALSE_FLAGS),
            ("higher", ws_ids[0], dict.fromkeys(FLAGS, True)),
            # Same name in another workspace must never supply the creator's grants.
            ("limited", ws_ids[1], dict.fromkeys(FLAGS, True)),
        ):
            row = CustomRole(
                workspace_id=wid, name=name, description="Original description", **flags
            )
            db.add(row)
            db.flush()
            definitions["foreign" if wid == ws_ids[1] else name] = row.id
        db.commit()
        assert db.get(CustomRole, 2147483647) is None
        app = FastAPI()
        app.include_router(members.router, prefix="/api")
        app.include_router(auth.router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        app.dependency_overrides[get_db] = database
        for actor in actors.values():
            actor["client"] = TestClient(app)
            actor["client"].cookies.set("tc_session", actor.pop("cookie"))
            clients.append(actor["client"])
        yield {"db": db, "actors": actors, "roles": definitions, "workspace": ws_ids[0]}
    finally:
        for client in clients:
            client.close()
        db.rollback()
        # These workspaces and actors were inserted by this fixture. Include
        # their API-created rows even if a request failed after committing.
        if ws_ids:
            db.query(AuditEvent).filter(
                or_(AuditEvent.workspace_id.in_(ws_ids), AuditEvent.user_id.in_(user_ids))
            ).delete(synchronize_session=False)
            db.query(CustomRole).filter(CustomRole.workspace_id.in_(ws_ids)).delete(
                synchronize_session=False
            )
            db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id.in_(ws_ids)).delete(
                synchronize_session=False
            )
        if user_ids:
            db.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        if ws_ids:
            db.query(Workspace).filter(Workspace.id.in_(ws_ids)).delete(synchronize_session=False)
        db.commit()
        assert snapshot(db) == baseline, "Owned cleanup changed pre-existing rows"
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def call(state, method, path, body, *, actor="limited", denied=None):
    before = snapshot(state["db"])
    response = state["actors"][actor]["client"].request(method, path, json=body)
    state["db"].expire_all()
    if denied is not None:
        assert response.status_code == denied
        assert snapshot(state["db"]) == before, "Denied definition mutation changed persisted rows"
    else:
        assert response.status_code == 200
    return response.json()


def role_path(state, name):
    return f"/api/members/roles/{state['roles'][name]}"


def permissions(state):
    response = state["actors"]["limited"]["client"].get("/api/auth/me")
    assert response.status_code == 200
    return response.json()["permissions"]


@pytest.mark.parametrize("flag", ("can_edit", "can_review", "can_export"))
def test_create_cannot_grant_a_permission_missing_from_current_actor(grants, flag):
    call(
        grants,
        "POST",
        "/api/members/roles",
        {"name": "over-granted", **FALSE_FLAGS, flag: True},
        denied=403,
    )


def test_default_review_permission_is_still_a_grant(grants):
    call(grants, "POST", "/api/members/roles", {"name": "implicit-review"}, denied=403)


@pytest.mark.parametrize("flag", ("can_edit", "can_review", "can_export"))
def test_self_patch_cannot_escalate_its_own_permission_snapshot(grants, flag):
    assert permissions(grants) == {**FALSE_FLAGS, "can_admin": True}
    call(
        grants,
        "PATCH",
        role_path(grants, "limited"),
        {flag: True, "description": "Must remain unchanged"},
        denied=403,
    )
    assert permissions(grants) == {**FALSE_FLAGS, "can_admin": True}


@pytest.mark.parametrize("flag", ("can_edit", "can_review", "can_export"))
def test_patch_other_role_cannot_enable_a_permission_the_actor_lacks(grants, flag):
    call(
        grants,
        "PATCH",
        role_path(grants, "empty"),
        {flag: True, "can_admin": True, "description": "Atomic denial"},
        denied=403,
    )


@pytest.mark.parametrize("flag", FLAGS)
def test_builtin_admin_can_create_and_enable_legitimate_grants(grants, flag):
    created = call(
        grants,
        "POST",
        "/api/members/roles",
        {"name": "legitimate", **FALSE_FLAGS, flag: True},
        actor="admin",
    )
    assert {key: created[key] for key in FLAGS} == {**FALSE_FLAGS, flag: True}
    changed = call(grants, "PATCH", role_path(grants, "empty"), {flag: True}, actor="admin")
    assert {key: changed[key] for key in FLAGS} == {**FALSE_FLAGS, flag: True}
    with Session(grants["db"].get_bind()) as db:
        events = (
            db.query(AuditEvent)
            .filter(AuditEvent.workspace_id == grants["workspace"])
            .order_by(AuditEvent.id)
            .all()
        )
        assert [event.action for event in events] == ["role.created", "role.updated"]


def test_limited_admin_can_grant_only_held_authority(grants):
    created = call(
        grants,
        "POST",
        "/api/members/roles",
        {"name": "delegated-admin", **FALSE_FLAGS, "can_admin": True},
    )
    assert {key: created[key] for key in FLAGS} == {**FALSE_FLAGS, "can_admin": True}
    changed = call(grants, "PATCH", role_path(grants, "empty"), {"can_admin": True})
    assert {key: changed[key] for key in FLAGS} == {**FALSE_FLAGS, "can_admin": True}


def test_partial_updates_preserve_unchanged_flags_and_allow_revocation(grants):
    changed = call(
        grants, "PATCH", role_path(grants, "higher"), {"description": "  New description  "}
    )
    assert changed["description"] == "New description"
    assert all(changed[key] is True for key in FLAGS)
    unchanged = call(
        grants, "PATCH", role_path(grants, "higher"), {"can_edit": True, "can_review": None}
    )
    assert all(unchanged[key] is True for key in FLAGS)
    revoked = call(grants, "PATCH", role_path(grants, "higher"), {"can_export": False})
    assert {key: revoked[key] for key in FLAGS} == {
        **dict.fromkeys(FLAGS, True),
        "can_export": False,
    }


def test_null_and_omitted_flags_never_enable_permissions(grants):
    changed = call(
        grants,
        "PATCH",
        role_path(grants, "limited"),
        {"can_edit": None, "description": "Safe edit"},
    )
    assert {key: changed[key] for key in FLAGS} == {**FALSE_FLAGS, "can_admin": True}
    assert call(grants, "PATCH", role_path(grants, "limited"), {}) == changed


def test_self_revocation_takes_effect_on_the_next_request(grants):
    call(grants, "PATCH", role_path(grants, "limited"), {"can_admin": False})
    assert permissions(grants) == FALSE_FLAGS
    call(
        grants,
        "POST",
        "/api/members/roles",
        {"name": "after-revocation", **FALSE_FLAGS},
        denied=403,
    )


def test_grant_snapshot_rechecks_current_flags_after_admin_revocation(grants):
    call(grants, "PATCH", role_path(grants, "limited"), {"can_edit": True}, actor="admin")
    call(
        grants,
        "POST",
        "/api/members/roles",
        {"name": "while-authorized", **FALSE_FLAGS, "can_edit": True},
    )
    call(grants, "PATCH", role_path(grants, "limited"), {"can_edit": False}, actor="admin")
    call(
        grants,
        "POST",
        "/api/members/roles",
        {"name": "after-demotion", **FALSE_FLAGS, "can_edit": True},
        denied=403,
    )
    call(grants, "PATCH", role_path(grants, "empty"), {"can_edit": True}, denied=403)


def test_foreign_and_missing_role_ids_retain_404_without_writes(grants):
    for path in (role_path(grants, "foreign"), "/api/members/roles/2147483647"):
        assert call(grants, "PATCH", path, {"can_edit": True}, denied=404) == {
            "detail": "Custom role not found"
        }


@pytest.mark.parametrize(
    "state,status", [("anonymous", 401), ("suspended", 403), ("removed", 403), ("no_admin", 403)]
)
def test_real_current_authority_is_required_for_create_and_update(grants, state, status):
    actor = grants["actors"]["limited"]
    if state == "anonymous":
        actor["client"].cookies.clear()
    elif state == "suspended":
        actor["member"].suspended = True
        grants["db"].commit()
    elif state == "removed":
        grants["db"].delete(actor["member"])
        grants["db"].commit()
    else:
        role = grants["db"].get(CustomRole, grants["roles"]["limited"])
        role.can_admin = False
        grants["db"].commit()
    call(
        grants,
        "POST",
        "/api/members/roles",
        {"name": "not-authorized", **FALSE_FLAGS, "can_admin": True},
        denied=status,
    )
    call(grants, "PATCH", role_path(grants, "empty"), {"can_admin": True}, denied=status)
