"""Role assignment and credential ceilings through real stored authorization.

SQLite and migrated PostgreSQL execute the same cases. Only database connection
seams are replaced. Invitations use the real console sender and acceptance routes;
issued bearer keys reach existing authorization-protected routes.
"""

import hashlib
import json
import re
import secrets
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes import auth, documents, members
from app.core import database
from app.core.session import sign_session
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    Invite,
    Subscription,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.models.in_app_notification import InAppNotification
from app.models.notification import NotificationPolicy
from app.services import email_service
from app.services.email_service import ConsoleEmailProvider, get_email_provider
from tests import _safety

FLAGS = ("can_edit", "can_review", "can_export", "can_admin")
NONE = dict.fromkeys(FLAGS, False)
LIMITED = {**NONE, "can_admin": True}
ALL = dict.fromkeys(FLAGS, True)
EXPECTED = {
    "empty": NONE,
    "limited": LIMITED,
    "higher": ALL,
    "admin": ALL,
    "editor": {**ALL, "can_admin": False},
    "reviewer": {**NONE, "can_review": True},
}
MODELS = (
    User,
    Workspace,
    WorkspaceMember,
    UserSession,
    UserMfa,
    Subscription,
    CustomRole,
    AuditEvent,
    ApiKey,
    Invite,
    InAppNotification,
    NotificationPolicy,
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
def grants(request, monkeypatch, capsys):
    # Other email tests can leave a mocked provider cached. Select the actual
    # provider from the scrubbed test environment, restoring the cache afterward.
    monkeypatch.setattr(email_service, "_default_provider", None)
    assert isinstance(get_email_provider(), ConsoleEmailProvider)
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
    outbound_before = _safety.blocked_attempts()
    # The genuine invitation background task must also use this owned database.
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    token = secrets.token_hex(8)
    ws_ids, user_ids, clients = [], [], []
    try:
        for name in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if wid not in ws_ids and db.get(Workspace, wid) is None:
                    break
            db.add(Workspace(id=wid, name=name, slug=f"entry-grants-{name}-{token}"))
            db.flush()
            ws_ids.append(wid)
        definitions = {}
        for name, wid, flags in (
            ("limited", ws_ids[0], LIMITED),
            ("empty", ws_ids[0], NONE),
            ("higher", ws_ids[0], ALL),
            *((field, ws_ids[0], {**NONE, field: True}) for field in FLAGS),
            ("limited", ws_ids[1], ALL),
            ("foreign-only", ws_ids[1], ALL),
        ):
            row = CustomRole(workspace_id=wid, name=name, **flags)
            db.add(row)
            db.flush()
            definitions["foreign-" + name if wid == ws_ids[1] else name] = row.id
        actors = {}
        for name, role, wid in (
            ("limited", "limited", ws_ids[0]),
            ("admin", "admin", ws_ids[0]),
            ("target", "empty", ws_ids[0]),
            ("high-target", "higher", ws_ids[0]),
            ("invitee", None, ws_ids[0]),
            ("foreign", "empty", ws_ids[1]),
        ):
            user = User(
                email=f"entry-grants-{name}-{token}@example.com", password_hash="synthetic-unused"
            )
            db.add(user)
            db.flush()
            user_ids.append(user.id)
            member = None
            if role:
                member = WorkspaceMember(workspace_id=wid, user_id=user.id, role=role)
                db.add(member)
                db.flush()
            sid = f"entry-grants-{name}-{token}"
            db.add(UserSession(user_id=user.id, session_id=sid))
            actors[name] = {
                "user_id": user.id,
                "email": user.email,
                "member": member,
                # Current membership/flags must override this stale admin claim.
                "cookie": sign_session(
                    user.id, user.email, wid, "admin", session_id=sid, max_age_seconds=3600
                ),
            }
        db.commit()
        assert db.get(WorkspaceMember, 2147483647) is None
        app = FastAPI()
        for module in (auth, members, documents):
            app.include_router(module.router, prefix="/api")

        def owned_database():
            with Session(engine) as current:
                yield current

        app.dependency_overrides[database.get_db] = owned_database
        for actor in actors.values():
            actor["client"] = TestClient(app)
            actor["client"].cookies.set("tc_session", actor.pop("cookie"))
            clients.append(actor["client"])
        yield {
            "db": db,
            "app": app,
            "actors": actors,
            "roles": definitions,
            "workspace": ws_ids[0],
            "capture": capsys,
        }
    finally:
        for client in clients:
            client.close()
        db.rollback()
        if ws_ids:
            for model in (InAppNotification, Invite, ApiKey, NotificationPolicy, CustomRole):
                db.query(model).filter(model.workspace_id.in_(ws_ids)).delete(
                    synchronize_session=False
                )
            db.query(AuditEvent).filter(
                or_(AuditEvent.workspace_id.in_(ws_ids), AuditEvent.user_id.in_(user_ids))
            ).delete(synchronize_session=False)
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
        assert _safety.blocked_attempts() == outbound_before, "Unexpected external network attempt"
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def call(state, method, path, body, *, actor="limited", status=200):
    before = snapshot(state["db"])
    threads_before = set(threading.enumerate())
    try:
        response = state["actors"][actor]["client"].request(method, path, json=body)
    finally:
        # Finish request-created background threads before snapshot/owned cleanup;
        # do not replace the actual invitation or email implementation.
        for thread in set(threading.enumerate()) - threads_before:
            thread.join(timeout=5)
            assert not thread.is_alive(), "Request background task did not finish"
    state["db"].expire_all()
    output = state["capture"].readouterr().out
    if path == "/api/members/invites":
        state["console_invitation"] = output
    assert response.status_code == status
    if status >= 400:
        assert snapshot(state["db"]) == before, "Denied grant changed persisted rows"
    if status == 500:
        return None
    return response.json()


def assign(state, role, *, target="target", actor="limited", status=200):
    member_id = state["actors"][target]["member"].id
    return call(
        state, "PATCH", f"/api/members/{member_id}", {"role": role}, actor=actor, status=status
    )


def issue(state, kind, role, *, actor="limited", status=200):
    if kind == "member":
        return assign(state, role, actor=actor, status=status)
    body = {"role": role}
    if kind == "invite":
        body["email"] = state["actors"]["invitee"]["email"]
    path = "invites" if kind == "invite" else "api-keys"
    return call(state, "POST", f"/api/members/{path}", body, actor=actor, status=status)


def permissions(state, actor="limited"):
    response = state["actors"][actor]["client"].get("/api/auth/me")
    assert response.status_code == 200
    return response.json()["permissions"]


def accept_console_invite(state):
    # Keep actual console email codes and one-time tokens in memory, not evidence.
    output = state.pop("console_invitation")
    match = re.search(r"Your verification code:\s+([^\s]+)", output)
    assert match is not None, "Console invitation was not sent"
    with TestClient(state["app"]) as guest:
        verified = guest.post(
            "/api/auth/verify-invite-code",
            json={"email": state["actors"]["invitee"]["email"], "code": match.group(1)},
        )
        assert verified.status_code == 200
        accepted = guest.post("/api/auth/accept-invite", json={"token": verified.json()["token"]})
        assert accepted.status_code == 200
    state["db"].expire_all()
    member = (
        state["db"]
        .query(WorkspaceMember)
        .filter_by(workspace_id=state["workspace"], user_id=state["actors"]["invitee"]["user_id"])
        .one()
    )
    assert state["db"].query(Invite).filter_by(workspace_id=state["workspace"]).count() == 0
    return member


@pytest.mark.parametrize("kind", ("member", "invite"))
@pytest.mark.parametrize("flag", ("can_edit", "can_review", "can_export"))
def test_missing_permission_cannot_be_granted_through_a_custom_role(grants, kind, flag):
    assert permissions(grants) == LIMITED
    issue(grants, kind, flag, status=403)


@pytest.mark.parametrize("kind", ("member", "invite", "key"))
@pytest.mark.parametrize("role", ("admin", "editor", "reviewer"))
def test_existing_builtin_roles_cannot_bypass_the_actor_ceiling(grants, kind, role):
    issue(grants, kind, role, status=403)


@pytest.mark.parametrize("role", ("admin", "higher"))
def test_self_assignment_does_not_expand_current_permissions(grants, role):
    # Preserve the existing last-admin guard; two builtin admins let both
    # requested roles reach the grant-ceiling check itself.
    assign(grants, "admin", target="high-target", actor="admin")
    assign(grants, role, target="limited", status=403)
    assert permissions(grants) == LIMITED


def test_default_editor_key_is_a_permission_grant(grants):
    call(grants, "POST", "/api/members/api-keys", {"label": "Default"}, status=403)


@pytest.mark.parametrize("flag", ("can_edit", "can_review", "can_export"))
def test_key_ceiling_checks_each_missing_permission_independently(grants, flag):
    role_id = grants["roles"]["limited"]
    call(grants, "PATCH", f"/api/members/roles/{role_id}", {**ALL, flag: False}, actor="admin")
    assert permissions(grants) == {**ALL, flag: False}
    issue(grants, "key", "admin", status=403)


def test_default_editor_key_remains_available_with_sufficient_authority(grants):
    issued = call(grants, "POST", "/api/members/api-keys", {}, actor="admin")
    assert issued["role"] == "editor"
    assert grants["db"].get(ApiKey, issued["id"]).role == "editor"
    with TestClient(grants["app"]) as service:
        headers = {"Authorization": "Bearer " + issued["key"]}
        response = service.post(
            f"/api/documents/bulk-delete?workspace_id={grants['workspace']}",
            json={"ids": []},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json() == {"deleted": 0, "errors": []}
        assert service.get("/api/members", headers=headers).status_code == 403


@pytest.mark.parametrize("kind", ("member", "invite"))
def test_held_admin_flag_can_be_delegated_without_other_grants(grants, kind):
    issue(grants, kind, "limited")
    if kind == "invite":
        assert accept_console_invite(grants).role == "limited"
        target = "invitee"
    else:
        target = "target"
    assert permissions(grants, target) == LIMITED


@pytest.mark.parametrize("role", ("higher", "admin", "editor", "reviewer", "empty"))
def test_unchanged_or_reduced_recipient_permissions_remain_allowed(grants, role):
    assign(grants, role, target="high-target")
    assert permissions(grants, "high-target") == EXPECTED[role]
    assert permissions(grants) == LIMITED


@pytest.mark.parametrize("kind", ("member", "invite", "key"))
def test_permitted_review_grants_use_current_flags_and_real_credentials(grants, kind):
    role_id = grants["roles"]["limited"]
    call(grants, "PATCH", f"/api/members/roles/{role_id}", {"can_review": True}, actor="admin")
    issued = issue(grants, kind, "reviewer")
    if kind == "key":
        assert grants["db"].get(ApiKey, issued["id"]).role == "reviewer"
        with TestClient(grants["app"]) as service:
            headers = {"Authorization": "Bearer " + issued["key"]}
            # This existing empty bulk request checks real edit authority
            # without any storage access or unrelated document mutation.
            edited = service.post(
                f"/api/documents/bulk-delete?workspace_id={grants['workspace']}",
                json={"ids": []},
                headers=headers,
            )
            assert edited.status_code == 403
            assert service.get("/api/members", headers=headers).status_code == 403
            assert service.get("/api/members").status_code == 401
    else:
        if kind == "invite":
            assert accept_console_invite(grants).role == "reviewer"
        assert (
            permissions(grants, "invitee" if kind == "invite" else "target") == EXPECTED["reviewer"]
        )


@pytest.mark.parametrize("kind", ("member", "invite", "key"))
def test_builtin_admin_can_grant_full_authority(grants, kind):
    issued = issue(grants, kind, "admin", actor="admin")
    if kind == "key":
        assert grants["db"].get(ApiKey, issued["id"]).role == "admin"
        with TestClient(grants["app"]) as service:
            response = service.post(
                f"/api/documents/bulk-delete?workspace_id={grants['workspace']}",
                json={"ids": []},
                headers={"Authorization": "Bearer " + issued["key"]},
            )
            assert response.status_code == 200
            assert response.json() == {"deleted": 0, "errors": []}
    else:
        if kind == "invite":
            assert accept_console_invite(grants).role == "admin"
        assert permissions(grants, "invitee" if kind == "invite" else "target") == ALL


@pytest.mark.parametrize("kind", ("member", "invite", "key"))
def test_same_cookie_obeys_current_permission_revocation(grants, kind):
    role_id = grants["roles"]["limited"]
    call(grants, "PATCH", f"/api/members/roles/{role_id}", {"can_review": True}, actor="admin")
    assert permissions(grants)["can_review"] is True
    call(grants, "PATCH", f"/api/members/roles/{role_id}", {"can_review": False}, actor="admin")
    issue(grants, kind, "reviewer", status=403)


@pytest.mark.parametrize("kind", ("member", "invite", "key"))
@pytest.mark.parametrize(
    "state,status", [("anonymous", 401), ("suspended", 403), ("removed", 403), ("no_admin", 403)]
)
def test_real_current_authority_required_on_each_grant_path(grants, kind, state, status):
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
        grants["db"].get(CustomRole, grants["roles"]["limited"]).can_admin = False
        grants["db"].commit()
    issue(grants, kind, "reviewer", status=status)


def test_missing_and_foreign_members_remain_indistinguishable(grants):
    foreign = grants["actors"]["foreign"]["member"].id
    for member_id in (foreign, 2147483647):
        assert call(
            grants, "PATCH", f"/api/members/{member_id}", {"role": "admin"}, status=404
        ) == {"detail": "Member not found"}


@pytest.mark.parametrize("kind", ("member", "invite", "key"))
@pytest.mark.parametrize("role", ("unknown", "foreign-only"))
def test_invalid_or_foreign_only_role_preserves_validation(grants, kind, role):
    issue(grants, kind, role, status=400)


def test_last_admin_cannot_demote_self(grants):
    result = assign(grants, "reviewer", target="admin", actor="admin", status=400)
    assert result == {"detail": "Transfer ownership to another admin before changing your role"}


def test_existing_invitation_validation_precedes_grant_checks(grants):
    call(grants, "POST", "/api/members/invites", {"email": "invalid", "role": "admin"}, status=400)
    call(
        grants,
        "POST",
        "/api/members/invites",
        {"email": grants["actors"]["target"]["email"], "role": "admin"},
        status=400,
    )
    issue(grants, "invite", "reviewer", actor="admin")
    issue(grants, "invite", "admin", status=400)


@pytest.mark.parametrize("kind", ("member", "invite"))
def test_target_role_lookup_failure_cannot_become_an_empty_grant(grants, kind):
    engine = grants["db"].get_bind()
    target_reads = 0

    def fail_after_validation(conn, cursor, statement, parameters, context, executemany):
        nonlocal target_reads
        values = parameters.values() if isinstance(parameters, dict) else parameters
        if "FROM custom_roles" in statement and "can_edit" in values:
            target_reads += 1
            if target_reads == 2:
                raise OperationalError(
                    "synthetic target role lookup failure", {}, RuntimeError("offline")
                )

    original = grants["actors"]["limited"]["client"]
    failing = TestClient(grants["app"], raise_server_exceptions=False)
    failing.cookies.update(original.cookies)
    grants["actors"]["limited"]["client"] = failing
    event.listen(engine, "before_cursor_execute", fail_after_validation)
    try:
        issue(grants, kind, "can_edit", status=500)
        assert target_reads == 2
    finally:
        event.remove(engine, "before_cursor_execute", fail_after_validation)
        grants["actors"]["limited"]["client"] = original
        failing.close()
    # The same real actor still lacks edit after the transient read failure.
    issue(grants, kind, "can_edit", status=403)
