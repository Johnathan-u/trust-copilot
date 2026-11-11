"""TC-06-003i: administrative article ownership with real stored human authority."""

import hashlib
import json
import logging
import secrets
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes.trust_articles import router
from app.core.database import get_db
from app.core.session import sign_session
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    PolicyAcknowledgment,
    TrustArticle,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from tests import _safety

MODELS = (
    User,
    Workspace,
    WorkspaceMember,
    UserSession,
    UserMfa,
    ApiKey,
    CustomRole,
    TrustArticle,
    PolicyAcknowledgment,
    AuditEvent,
)
PATH = "/api/trust-articles"
MISSING = 2147483647


def snapshot(db):
    """Hash every column of every row, retaining IDs for precise mutation checks."""
    return {
        model.__tablename__: {
            row["id"]: hashlib.sha256(
                json.dumps(dict(row), sort_keys=True, default=str).encode()
            ).hexdigest()
            for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
        }
        for model in MODELS
    }


def changed_rows(before, after):
    return {
        table: changed
        for table in before
        if (
            changed := {
                row_id
                for row_id in before[table].keys() | after[table].keys()
                if before[table].get(row_id) != after[table].get(row_id)
            }
        )
    }


@pytest.fixture(params=("sqlite", "postgres"))
def articles(request, caplog):
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
    owned = {model: set() for model in MODELS}
    clients = []
    caplog.set_level(logging.INFO, logger="trustcopilot.audit")

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].add(row.id)
        return row

    def remember_created(session, _context):
        for row in session.new:
            if type(row) in owned:
                owned[type(row)].add(row.id)

    try:
        token = secrets.token_hex(8)
        workspaces, users, members, sessions = [], [], [], []
        for label in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if db.get(Workspace, wid) is None:
                    break
            ws = add(Workspace, id=wid, name=label, slug=f"article-{label}-{token}")
            user = add(User, email=f"article-{label}-{token}@example.com", password_hash="unused")
            member = add(WorkspaceMember, workspace_id=wid, user_id=user.id, role="admin")
            sid = add(UserSession, user_id=user.id, session_id=f"article-{label}-{token}")
            workspaces.append(ws)
            users.append(user)
            members.append(member)
            sessions.append(sid)
        rows = {}
        for label, wid in (
            ("own", workspaces[0].id),
            ("foreign", workspaces[1].id),
            ("null", None),
        ):
            for published in (0, 1):
                rows[f"{label}_{published}"] = add(
                    TrustArticle,
                    workspace_id=wid,
                    slug=f"{token}-{label}-{published}",
                    title=f"Synthetic {label} {published}",
                    content=f"Synthetic {label} private content {published}",
                    category="security",
                    published=published,
                    is_policy=True,
                )
        db.commit()
        assert db.get(TrustArticle, MISSING) is None
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                event.listen(current, "after_flush", remember_created)
                yield current

        app.dependency_overrides[get_db] = database
        clients = [TestClient(app, raise_server_exceptions=False) for _ in range(3)]

        def cookie(index=0, **overrides):
            options = {"session_id": sessions[index].session_id, "max_age_seconds": 3600}
            options.update(overrides)
            clients[index].cookies.clear()
            clients[index].cookies.set(
                "tc_session",
                sign_session(
                    users[index].id,
                    users[index].email,
                    workspaces[index].id,
                    "admin",
                    **options,
                ),
            )

        cookie(0)
        cookie(1)
        yield {
            "db": db,
            "engine": engine,
            "clients": clients,
            "workspaces": workspaces,
            "users": users,
            "members": members,
            "sessions": sessions,
            "rows": rows,
            "add": add,
            "cookie": cookie,
            "caplog": caplog,
            "token": token,
        }
    finally:
        for client in clients:
            client.close()
        db.rollback()
        for model in reversed(MODELS):
            if owned[model]:
                db.query(model).filter(model.id.in_(owned[model])).delete(synchronize_session=False)
        db.commit()
        assert snapshot(db) == baseline, "Owned cleanup changed pre-existing complete rows"
        assert _safety.blocked_attempts() == outbound_before
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def call(state, method, path, *, body=None, status=200, client=0, writable=False):
    before = snapshot(state["db"])
    statements = []
    audit_before = len(state["caplog"].records)

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(state["engine"], "before_cursor_execute", capture)
    try:
        response = state["clients"][client].request(method, path, json=body)
    finally:
        event.remove(state["engine"], "before_cursor_execute", capture)
    state["db"].expire_all()
    changes = changed_rows(before, snapshot(state["db"]))
    state["changes"] = changes
    state["statements"] = statements
    state["audit"] = [
        json.loads(record.getMessage().removeprefix("audit "))
        for record in state["caplog"].records[audit_before:]
        if record.name == "trustcopilot.audit"
    ]
    assert response.status_code == status, response.text
    if not writable:
        assert not changes, changes
        assert {sql.lstrip().split(None, 1)[0].upper() for sql in statements} <= {"SELECT"}
        assert not state["audit"]
    return response.json()


def creation_body(state, variant="omitted", **fields):
    body = {"slug": f"new-{state['token']}", "title": "Created article", "published": 0}
    if variant != "omitted":
        body["workspace_id"] = {
            "null": None,
            "zero": 0,
            "own": state["workspaces"][0].id,
        }[variant]
    return body | fields


@pytest.mark.parametrize("variant", ("omitted", "null", "zero", "own"))
def test_create_binds_effective_workspace_and_is_readable_by_creator(articles, variant):
    state = articles
    body = creation_body(state, variant, content="Owned private text", is_policy=True)
    result = call(state, "POST", PATH + "/", body=body, writable=True)
    aid = result["id"]
    assert state["changes"] == {"trust_articles": {aid}}
    assert result["workspace_id"] == state["workspaces"][0].id
    assert result["slug"] == body["slug"] and result["content"] == "Owned private text"
    assert result["published"] == 0 and result["is_policy"] is True
    assert state["db"].get(TrustArticle, aid).workspace_id == state["workspaces"][0].id
    assert len(state["audit"]) == 1
    assert state["audit"][0] | {"ts": None} == {
        "ts": None,
        "action": "trust_article.create",
        "email": state["users"][0].email,
        "workspace_id": state["workspaces"][0].id,
        "resource_type": "trust_article",
        "resource_id": aid,
        "slug": body["slug"],
    }
    assert call(state, "GET", f"{PATH}/{aid}") == result
    call(state, "GET", f"{PATH}/{aid}", client=1, status=404)
    call(state, "GET", f"{PATH}/{aid}", client=2, status=404)


@pytest.mark.parametrize("variant", ("omitted", "null", "zero", "own"))
def test_duplicate_lookup_uses_effective_workspace_without_writing(articles, variant):
    slug = articles["rows"]["own_0"].slug
    result = call(
        articles,
        "POST",
        PATH + "/",
        body=creation_body(articles, variant, slug=slug),
        status=400,
    )
    assert result == {"detail": f"Slug '{slug}' already exists"}


@pytest.mark.parametrize("owner", ("foreign", "null"))
def test_foreign_or_unowned_slug_does_not_block_owned_creation(articles, owner):
    slug = articles["rows"][f"{owner}_0"].slug
    result = call(
        articles, "POST", PATH + "/", body=creation_body(articles, slug=slug), writable=True
    )
    assert articles["changes"] == {"trust_articles": {result["id"]}}
    assert result["workspace_id"] == articles["workspaces"][0].id and result["slug"] == slug


@pytest.mark.parametrize("target", ("foreign", "missing", "negative"))
def test_explicit_foreign_workspace_create_keeps_403(articles, target):
    wid = {"foreign": articles["workspaces"][1].id, "missing": MISSING, "negative": -1}[target]
    result = call(
        articles,
        "POST",
        PATH + "/",
        body=creation_body(articles, workspace_id=wid),
        status=403,
    )
    assert result == {"detail": "Access denied"}
    assert not any("trust_articles" in sql for sql in articles["statements"])


@pytest.mark.parametrize("method", ("PATCH", "DELETE"))
@pytest.mark.parametrize(
    "target", ("foreign_0", "foreign_1", "null_0", "null_1", "moved", "deleted", "missing")
)
def test_mutations_require_current_exact_article_owner(articles, method, target):
    state = articles
    row = state["rows"].get(target, state["rows"]["own_0"])
    aid, status = row.id, 403
    if target == "moved":
        row.workspace_id = state["workspaces"][1].id
    elif target == "deleted":
        state["db"].delete(row)
        status = 404
    elif target == "missing":
        aid, status = MISSING, 404
    state["db"].commit()
    result = call(
        state,
        method,
        f"{PATH}/{aid}",
        body={"title": "Unauthorized rewrite"} if method == "PATCH" else None,
        status=status,
    )
    assert result == {"detail": "Access denied" if status == 403 else "Trust article not found"}


def test_owned_patch_and_delete_change_only_intended_rows(articles):
    state = articles
    row = state["rows"]["own_0"]
    aid, created = row.id, row.created_at.isoformat()
    values = {
        "slug": f"edited-{state['token']}",
        "title": "Edited title",
        "content": "Edited content",
        "category": "privacy",
        "published": 1,
        "is_policy": False,
    }
    result = call(state, "PATCH", f"{PATH}/{aid}", body=values, writable=True)
    assert state["changes"] == {"trust_articles": {aid}}
    assert result | {"updated_at": None} == values | {
        "id": aid,
        "workspace_id": state["workspaces"][0].id,
        "created_at": created,
        "updated_at": None,
    }
    duplicate = state["rows"]["own_1"].slug
    call(state, "PATCH", f"{PATH}/{aid}", body={"slug": duplicate}, status=400)
    ack = state["add"](
        PolicyAcknowledgment,
        user_id=state["users"][0].id,
        trust_article_id=aid,
        acknowledged_at=datetime(2026, 1, 1),
    )
    ack_id = ack.id
    state["db"].commit()
    assert call(state, "DELETE", f"{PATH}/{aid}", writable=True) == {"ok": True}
    assert state["changes"] == {"trust_articles": {aid}, "policy_acknowledgments": {ack_id}}
    assert len(state["audit"]) == 1
    assert state["audit"][0]["action"] == "trust_article.delete"
    assert state["audit"][0]["workspace_id"] == state["workspaces"][0].id
    assert state["audit"][0]["resource_id"] == aid
    call(state, "GET", f"{PATH}/{aid}", status=404)


@pytest.mark.parametrize("method", ("POST", "PATCH", "DELETE"))
@pytest.mark.parametrize("role", ("editor", "reviewer", "custom_no_admin", "foreign_custom_admin"))
def test_current_role_cannot_use_stale_admin_cookie(articles, method, role):
    state = articles
    state["members"][0].role = role
    if "custom" in role:
        state["add"](
            CustomRole,
            workspace_id=state["workspaces"][int(role == "foreign_custom_admin")].id,
            name=role,
            can_admin=role == "foreign_custom_admin",
        )
    state["db"].commit()
    path = PATH + "/" if method == "POST" else f"{PATH}/{state['rows']['own_0'].id}"
    call(state, method, path, body=creation_body(state), status=403)
    assert not any("trust_articles" in sql for sql in state["statements"])


@pytest.mark.parametrize("method", ("POST", "PATCH", "DELETE"))
def test_current_custom_admin_retains_owned_mutation_permission(articles, method):
    state = articles
    state["members"][0].role = "custom-admin"
    state["add"](
        CustomRole, workspace_id=state["workspaces"][0].id, name="custom-admin", can_admin=True
    )
    state["db"].commit()
    aid = state["rows"]["own_0"].id
    path = PATH + "/" if method == "POST" else f"{PATH}/{aid}"
    result = call(state, method, path, body=creation_body(state), writable=True)
    expected_id = result["id"] if method == "POST" else aid
    assert state["changes"] == {"trust_articles": {expected_id}}
    if method != "DELETE":
        assert result["workspace_id"] == state["workspaces"][0].id


@pytest.mark.parametrize("method", ("POST", "PATCH", "DELETE"))
@pytest.mark.parametrize(
    "authority,status",
    (
        ("anonymous", 401),
        ("expired", 401),
        ("revoked", 401),
        ("wrong_user", 401),
        ("suspended", 403),
        ("removed", 403),
    ),
)
def test_current_authority_loss_denies_admin_writes(articles, method, authority, status):
    state = articles
    if authority == "anonymous":
        state["clients"][0].cookies.clear()
    elif authority == "expired":
        state["cookie"](max_age_seconds=-1)
    elif authority == "revoked":
        state["db"].delete(state["sessions"][0])
    elif authority == "wrong_user":
        state["sessions"][0].user_id = state["users"][1].id
    elif authority == "suspended":
        state["members"][0].suspended = True
    else:
        state["db"].delete(state["members"][0])
    state["db"].commit()
    path = PATH + "/" if method == "POST" else f"{PATH}/{state['rows']['own_0'].id}"
    call(state, method, path, body=creation_body(state), status=status)
    assert not any("trust_articles" in sql for sql in state["statements"])
    # Optional authentication continues to permit explicitly published content.
    assert call(state, "GET", f"{PATH}/{state['rows']['own_1'].id}")["published"] == 1
    call(state, "GET", f"{PATH}/{state['rows']['own_0'].id}", status=404)


def test_signed_reads_ignore_foreign_query_workspace_and_preserve_private_scope(articles):
    state = articles
    result = call(state, "GET", f"{PATH}?workspace_id={state['workspaces'][1].id}")
    assert {row["id"] for row in result} == {state["rows"]["own_0"].id, state["rows"]["own_1"].id}
    for target in ("foreign_0", "foreign_1", "null_0", "null_1"):
        call(state, "GET", f"{PATH}/{state['rows'][target].id}", status=404)


def test_anonymous_published_access_remains_explicitly_public(articles):
    state = articles
    for label in ("own", "foreign", "null"):
        public = state["rows"][f"{label}_1"]
        assert call(state, "GET", f"{PATH}/{public.id}", client=2)["content"] == public.content
        call(state, "GET", f"{PATH}/{state['rows'][f'{label}_0'].id}", client=2, status=404)
    listed = call(
        state,
        "GET",
        f"{PATH}?published_only=true&workspace_id={state['workspaces'][0].id}",
        client=2,
    )
    assert [row["id"] for row in listed] == [state["rows"]["own_1"].id]
    call(state, "GET", PATH, client=2, status=401)
    call(state, "GET", f"{PATH}?workspace_id={state['workspaces'][0].id}", client=2, status=401)


def test_policy_acknowledgment_scope_and_idempotent_retry_are_preserved(articles):
    state = articles
    aid = state["rows"]["own_0"].id
    for target in ("foreign_0", "null_0"):
        call(state, "POST", f"{PATH}/{state['rows'][target].id}/acknowledge", status=404)
    call(state, "POST", f"{PATH}/{aid}/acknowledge", client=2, status=401)
    result = call(state, "POST", f"{PATH}/{aid}/acknowledge", writable=True)
    assert result["ok"] is True and datetime.fromisoformat(result["acknowledged_at"])
    assert set(state["changes"]) == {"policy_acknowledgments"}
    assert len(state["changes"]["policy_acknowledgments"]) == 1
    assert call(state, "POST", f"{PATH}/{aid}/acknowledge")["ok"] is True
    assert call(state, "GET", PATH + "/policy-acknowledgments") == {
        "acknowledged_article_ids": [aid]
    }
    state["rows"]["own_0"].workspace_id = state["workspaces"][1].id
    state["db"].commit()
    assert call(state, "GET", PATH + "/policy-acknowledgments") == {"acknowledged_article_ids": []}
    call(state, "POST", f"{PATH}/{aid}/acknowledge", status=404)
