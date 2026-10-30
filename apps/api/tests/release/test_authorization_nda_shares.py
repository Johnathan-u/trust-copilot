"""Administrative NDA/share object scope; public token capabilities stay public.

Real stored auth and SQL on FK-enforced SQLite and migrated PostgreSQL. No auth,
service, token-generation or SQL mocks substitute for the required database run.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import nda_access, shareable_spaces
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    NdaAccessRequest,
    ShareableSpace,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)

MODELS = (
    NdaAccessRequest,
    ShareableSpace,
    AuditEvent,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
ACTIONS = ("approve", "reject", "revoke", "deactivate")
STATUSES = ("pending", "approved", "rejected", "revoked", "expired")


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def snapshot(db):
    result = {}
    for model in MODELS:
        rows = [list(row) for row in db.execute(select(model.__table__).order_by(model.id))]
        encoded = json.dumps(rows, default=lambda value: value.isoformat(), sort_keys=True).encode()
        result[model.__tablename__] = (len(rows), hashlib.sha256(encoded).hexdigest())
    return result


@pytest.fixture(
    params=(
        pytest.param("sqlite", marks=pytest.mark.unit),
        pytest.param("postgres", marks=pytest.mark.integration),
    )
)
def store(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        from app.core.database import SessionLocal

        db = SessionLocal()
        engine = db.get_bind()
        assert engine.dialect.name == "postgresql"
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        Base.metadata.create_all(engine, tables=[model.__table__ for model in MODELS])
        db = Session(engine)
    before = snapshot(db)
    owned = {model: [] for model in MODELS}
    clients = []

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        suffix = secrets.token_hex(8)
        next_ws = int(db.scalar(select(func.max(Workspace.id))) or 0) + 1
        workspaces = [
            add(Workspace, id=next_ws + i, name="NDA/share", slug=f"nda-share-{suffix}-{i}")
            for i in range(2)
        ]
        users = [
            add(User, email=f"nda-share-{suffix}-{i}@example.com", password_hash="unused")
            for i in range(2)
        ]
        members = [
            add(WorkspaceMember, workspace_id=workspaces[i].id, user_id=users[i].id, role="admin")
            for i in range(2)
        ]
        add(
            CustomRole,
            workspace_id=workspaces[0].id,
            name="session_only",
            can_review=False,
            can_edit=False,
            can_admin=False,
            can_export=False,
        )
        sid = secrets.token_hex(24)
        session = add(UserSession, user_id=users[0].id, session_id=sid)
        db.commit()

        def make(kind="nda", target="own", status="approved"):
            token = secrets.token_urlsafe(32)
            if target == "missing":
                return {"id": 2147483647, "kind": kind, "token": token}
            index = 1 if target == "foreign" else 0
            fields = dict(
                workspace_id=workspaces[index].id,
                access_token=token,
                expires_at=now() + timedelta(days=10),
            )
            if kind == "nda":
                row = add(
                    NdaAccessRequest,
                    **fields,
                    requester_name="Synthetic Buyer",
                    requester_email="synthetic-buyer@example.com",
                    requester_company="Synthetic Company",
                    purpose="Synthetic private purpose",
                    nda_accepted=True,
                    nda_accepted_at=now(),
                    status=status,
                    approved_by_user_id=users[index].id,
                )
            else:
                row = add(
                    ShareableSpace,
                    **fields,
                    name="Synthetic private share",
                    buyer_company="Synthetic Company",
                    buyer_email="synthetic-buyer@example.com",
                    opportunity_id="synthetic-opportunity",
                    is_active=True,
                    article_ids_json="[101]",
                    answer_ids_json="[201]",
                    document_ids_json="[301]",
                    created_by_user_id=users[index].id,
                )
            record = {"id": row.id, "kind": kind, "token": token}
            if target == "moved":
                row.workspace_id = workspaces[1].id
            elif target == "deleted":
                db.delete(row)
            db.commit()
            return record

        app = FastAPI()
        app.include_router(nda_access.router, prefix="/api")
        app.include_router(shareable_spaces.router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        app.dependency_overrides[get_db] = database
        client, public = TestClient(app), TestClient(app)
        clients.extend([client, public])
        client.cookies.set(
            "tc_session",
            sign_session(
                users[0].id,
                users[0].email,
                workspaces[0].id,
                "admin",
                session_id=sid,
                max_age_seconds=3600,
            ),
        )
        yield dict(
            db=db,
            engine=engine,
            client=client,
            public=public,
            make=make,
            ws=[row.id for row in workspaces],
            user=users[0].id,
            member=members[0],
            session=session,
        )
    finally:
        for client in clients:
            client.close()
        db.rollback()
        try:
            for model in MODELS:
                if owned[model]:
                    db.query(model).filter(model.id.in_(owned[model])).delete(
                        synchronize_session=False
                    )
            db.commit()
            assert snapshot(db) == before
        finally:
            db.close()
            if request.param == "sqlite":
                engine.dispose()


def model_for(record):
    return NdaAccessRequest if record["kind"] == "nda" else ShareableSpace


def capability(store, record, token=None):
    assert not store["public"].cookies
    route = (
        "/api/nda-access/validate" if record["kind"] == "nda" else "/api/shareable-spaces/access"
    )
    response = store["public"].get(
        route, params={"token": record["token"] if token is None else token}
    )
    assert response.status_code == 200
    return response.json()


def call(store, action, record, days=None):
    route = (
        f'/api/shareable-spaces/{record["id"]}/deactivate'
        if action == "deactivate"
        else f'/api/nda-access/{action}/{record["id"]}'
    )
    return store["client"].post(route, params={} if days is None else {"access_days": days})


def deny_without_writes(store, action, record, status=404, days=None):
    db = store["db"]
    before = snapshot(db)
    original_capability = capability(store, record)
    writes = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(store["engine"], "before_cursor_execute", capture)
    try:
        response = call(store, action, record, days)
    finally:
        event.remove(store["engine"], "before_cursor_execute", capture)
    assert response.status_code == status
    if status == 404:
        assert response.json() == {
            "detail": "Not Found" if action == "deactivate" else "Request not found"
        }
    assert not writes, "Authorization must precede writes, even writes later rolled back"
    assert not db.new and not db.dirty and not db.deleted
    assert capability(store, record) == original_capability
    assert snapshot(db) == before


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("target", ["foreign", "moved", "deleted", "missing"])
def test_unavailable_object_denied_without_changing_capability(store, action, target):
    record = store["make"]("share" if action == "deactivate" else "nda", target)
    assert capability(store, record)["valid"] == (target in ("foreign", "moved"))
    deny_without_writes(store, action, record)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("role", ["admin", "editor", "reviewer", "session_only"])
def test_current_admin_permission_is_preserved(store, action, role):
    store["member"].role = role  # Signed cookie remains admin; current stored role wins.
    store["db"].commit()
    record = store["make"]("share" if action == "deactivate" else "nda")
    if role == "admin":
        assert call(store, action, record).status_code == 200
    else:
        deny_without_writes(store, action, record, status=403)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("revocation", ["suspended", "membership_removed", "session_removed"])
def test_stale_authority_cannot_change_objects_or_capabilities(store, action, revocation):
    record = store["make"]("share" if action == "deactivate" else "nda")
    if revocation == "suspended":
        store["member"].suspended = True
    elif revocation == "membership_removed":
        store["db"].delete(store["member"])
    else:
        store["db"].delete(store["session"])
    store["db"].commit()
    deny_without_writes(
        store, action, record, status=401 if revocation == "session_removed" else 403
    )


@pytest.mark.parametrize("action", ["approve", "reject", "revoke"])
@pytest.mark.parametrize("status", STATUSES)
def test_owned_nda_preserves_all_existing_transitions_and_token_behavior(store, action, status):
    record = store["make"](status=status)
    row = store["db"].get(NdaAccessRequest, record["id"])
    old_expiry, old_acceptance = row.expires_at, row.nda_accepted_at
    before = now()
    response = call(store, action, record)
    assert response.status_code == 200
    body = response.json()
    expected = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}[action]
    assert body["status"] == expected and body["workspace_id"] == store["ws"][0]
    assert body["requester_email"] == "synthetic-buyer@example.com"
    store["db"].expire_all()
    row = store["db"].get(NdaAccessRequest, record["id"])
    assert row.status == expected and row.nda_accepted_at == old_acceptance
    assert row.access_token == body["access_token"]
    if action == "approve":
        assert row.approved_by_user_id == store["user"]
        assert row.access_token and row.access_token != record["token"]
        assert before + timedelta(days=30) <= row.expires_at <= now() + timedelta(days=30)
        assert capability(store, record, body["access_token"])["valid"]
        assert not capability(store, record)["valid"]
    else:
        assert row.access_token == record["token"] and row.expires_at == old_expiry
        assert not capability(store, record)["valid"]
        if action == "revoke":
            assert before <= row.revoked_at <= now()


@pytest.mark.parametrize("days", [1, 30, 365])
def test_owned_approval_preserves_access_duration(store, days):
    record = store["make"]()
    before = now()
    response = call(store, "approve", record, days)
    assert response.status_code == 200
    store["db"].expire_all()
    row = store["db"].get(NdaAccessRequest, record["id"])
    assert before + timedelta(days=days) <= row.expires_at <= now() + timedelta(days=days)
    assert capability(store, record, response.json()["access_token"])["valid"]


@pytest.mark.parametrize("days", [0, 366])
def test_invalid_duration_preserves_object_and_existing_token(store, days):
    record = store["make"]()
    deny_without_writes(store, "approve", record, status=422, days=days)


def test_owned_share_deactivation_is_repeatable_and_preserves_projection(store):
    record = store["make"]("share")
    assert capability(store, record)["valid"]
    response = call(store, "deactivate", record)
    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == store["ws"][0] and body["access_token"] == record["token"]
    assert body["buyer_email"] == "synthetic-buyer@example.com" and body["is_active"] is False
    store["db"].expire_all()
    assert store["db"].get(ShareableSpace, record["id"]).is_active is False
    assert capability(store, record) == {"valid": False, "reason": "Space deactivated"}
    before = snapshot(store["db"])
    again = call(store, "deactivate", record)
    assert again.status_code == 200 and again.json() == body
    assert snapshot(store["db"]) == before


@pytest.mark.parametrize("kind", ["nda", "share"])
@pytest.mark.parametrize("state", ["valid", "unknown", "expired", "disabled"])
def test_public_capability_semantics_remain_unchanged(store, kind, state):
    record = store["make"](kind, "foreign")
    row = store["db"].get(model_for(record), record["id"])
    if state == "expired":
        row.expires_at = now() - timedelta(days=1)
    elif state == "disabled":
        if kind == "nda":
            row.status = "revoked"
        else:
            row.is_active = False
    elif state == "unknown":
        record["token"] = secrets.token_urlsafe(32)
    store["db"].commit()
    before = snapshot(store["db"])
    result = capability(store, record)
    assert result["valid"] == (state == "valid")
    if state == "valid":
        if kind == "nda":
            assert result["workspace_id"] == store["ws"][1]
        else:
            assert result["space"]["workspace_id"] == store["ws"][1]
            assert result["article_ids"] == [101] and result["answer_ids"] == [201]
            assert result["document_ids"] == [301]
    assert snapshot(store["db"]) == before


@pytest.mark.parametrize("kind", ["nda", "share"])
def test_lists_keep_current_workspace_scope(store, kind):
    own, foreign = store["make"](kind), store["make"](kind, "foreign")
    before = snapshot(store["db"])
    path, key = (
        ("/api/nda-access/requests", "requests")
        if kind == "nda"
        else ("/api/shareable-spaces", "spaces")
    )
    response = store["client"].get(path)
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()[key]}
    assert ids == {own["id"]} and foreign["id"] not in ids
    assert snapshot(store["db"]) == before
