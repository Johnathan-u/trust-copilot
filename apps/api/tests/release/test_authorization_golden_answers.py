"""Golden-library object authorization with actual stored auth and FK-enforced data.

SQLite controls are local regressions; the same cases require migrated PostgreSQL
for release qualification. No auth, route, service or SQL mocks are used.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.golden_answers import router
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    AnswerApprovalEvent,
    ApiKey,
    AuditEvent,
    CustomRole,
    GoldenAnswer,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)

MODELS = (
    AnswerApprovalEvent,
    GoldenAnswer,
    AuditEvent,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
ACTIONS = ("get", "lineage", "update", "review", "reuse")
UNAVAILABLE = ("foreign", "moved", "deleted", "missing")


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
    client = None

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        suffix = secrets.token_hex(8)
        # Existing migrated seeds use explicit workspace IDs. Leave sequences alone.
        next_ws = int(db.scalar(select(func.max(Workspace.id))) or 0) + 1
        ws = [
            add(Workspace, id=next_ws + i, name="Approval", slug=f"approval-{suffix}-{i}")
            for i in range(2)
        ]
        users = [
            add(User, email=f"approval-{suffix}-{i}@example.com", password_hash="unused")
            for i in range(3)
        ]
        actor = add(WorkspaceMember, workspace_id=ws[0].id, user_id=users[0].id, role="admin")
        assignee = add(WorkspaceMember, workspace_id=ws[0].id, user_id=users[1].id, role="reviewer")
        add(WorkspaceMember, workspace_id=ws[1].id, user_id=users[2].id, role="admin")
        add(
            CustomRole,
            workspace_id=ws[0].id,
            name="session_only",
            can_review=False,
            can_edit=False,
            can_admin=False,
            can_export=False,
        )
        sid = secrets.token_hex(24)
        session = add(UserSession, user_id=users[0].id, session_id=sid)
        db.commit()

        def answer(status="pending_review", target="own"):
            if target == "missing":
                return 2147483647
            row = add(
                GoldenAnswer,
                workspace_id=ws[1].id if target == "foreign" else ws[0].id,
                question_text="Synthetic private golden question",
                answer_text="Synthetic private golden answer",
                status=status,
                review_cycle_days=17,
                review_sla_hours=24,
                submitted_at=datetime.now() - timedelta(days=4),
            )
            ga_id = row.id
            add(
                AnswerApprovalEvent,
                golden_answer_id=ga_id,
                action="submitted",
                actor_user_id=users[2].id if target == "foreign" else users[0].id,
                comment="Synthetic existing approval comment",
            )
            if target == "moved":
                row.workspace_id = ws[1].id
            elif target == "deleted":
                db.delete(row)
            db.commit()
            if target == "deleted":
                assert not db.scalar(
                    select(AnswerApprovalEvent.id).where(
                        AnswerApprovalEvent.golden_answer_id == ga_id
                    )
                )
            return ga_id

        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        app.dependency_overrides[get_db] = database
        client = TestClient(app)
        client.cookies.set(
            "tc_session",
            sign_session(
                users[0].id, users[0].email, ws[0].id, "admin", session_id=sid, max_age_seconds=3600
            ),
        )
        yield dict(
            db=db,
            engine=engine,
            client=client,
            answer=answer,
            add=add,
            ws=[w.id for w in ws],
            users=[u.id for u in users],
            actor=actor,
            assignee=assignee,
            session=session,
            owned=owned,
        )
    finally:
        if client:
            client.close()
        db.rollback()
        try:
            # Route-created events belong to exact fixture-owned parent IDs. Resolve
            # their exact IDs before cleanup, including failures partway through a test.
            owned[AnswerApprovalEvent] = list(
                db.scalars(
                    select(AnswerApprovalEvent.id).where(
                        AnswerApprovalEvent.golden_answer_id.in_(owned[GoldenAnswer])
                    )
                )
            )
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


def call(store, action, ga_id, body=None):
    method, suffix = {
        "get": ("GET", f"/{ga_id}"),
        "lineage": ("GET", f"/{ga_id}/lineage"),
        "update": ("PATCH", f"/{ga_id}"),
        "review": ("POST", f"/{ga_id}/review"),
        "reuse": ("POST", f"/{ga_id}/reuse"),
    }[action]
    if action == "update" and body is None:
        body = {"answer_text": "Synthetic updated answer", "status": "rejected"}
    return store["client"].request(
        method, "/api/golden-answers" + suffix, **({"json": body} if body is not None else {})
    )


def deny_without_writes(store, action, ga_id, status=404):
    db = store["db"]
    before = snapshot(db)
    writes = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(store["engine"], "before_cursor_execute", capture)
    try:
        response = call(store, action, ga_id)
    finally:
        event.remove(store["engine"], "before_cursor_execute", capture)
    assert response.status_code == status, response.text
    if status == 404:
        assert response.json() == {
            "detail": "Golden answer not found" if action == "lineage" else "Not Found"
        }
    assert not writes, "Authorization must precede writes, even writes later rolled back"
    assert not db.new and not db.dirty and not db.deleted
    assert snapshot(db) == before


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("target", UNAVAILABLE)
def test_unavailable_parent_preserves_neutral_route_404(store, action, target):
    ga_id = store["answer"](target=target)
    deny_without_writes(store, action, ga_id)


def test_lineage_checks_foreign_parent_before_decoding_private_fields(store):
    ga_id = store["answer"](target="foreign")
    store["db"].get(GoldenAnswer, ga_id).control_ids_json = "{malformed"
    store["db"].commit()
    deny_without_writes(store, "lineage", ga_id)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("role", ["admin", "editor", "reviewer", "session_only"])
def test_current_permissions_preserve_existing_route_contract(store, action, role):
    store["actor"].role = role  # Stale admin cookie cannot grant current admin permission.
    store["db"].commit()
    ga_id = store["answer"]()
    if action in ("update", "review") and role != "admin":
        deny_without_writes(store, action, ga_id, status=403)
    else:
        response = call(store, action, ga_id)
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("revocation", ["suspended", "membership_removed", "session_removed"])
def test_stale_authority_denied_without_object_mutation(store, action, revocation):
    ga_id = store["answer"]()
    if revocation == "suspended":
        store["actor"].suspended = True
    elif revocation == "membership_removed":
        store["db"].delete(store["actor"])
    else:
        store["db"].delete(store["session"])
    store["db"].commit()
    deny_without_writes(
        store, action, ga_id, status=401 if revocation == "session_removed" else 403
    )


@pytest.mark.parametrize("action", ["get", "lineage"])
def test_owned_detail_and_lineage_preserve_projection_without_writes(store, action):
    ga_id = store["answer"]()
    row = store["db"].get(GoldenAnswer, ga_id)
    row.control_ids_json, row.evidence_ids_json = "[101, 102]", "[201]"
    row.source_answer_id = 301
    row.owner_user_id = store["users"][0]
    row.customer_override_for = "Synthetic customer"
    store["db"].commit()
    before = snapshot(store["db"])
    response = call(store, action, ga_id)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == ga_id and body["question_text"] == "Synthetic private golden question"
    assert body["answer_text"] == "Synthetic private golden answer"
    assert body["source_answer_id"] == 301 and body["customer_override_for"] == "Synthetic customer"
    if action == "lineage":
        assert body["control_ids"] == [101, 102] and body["evidence_ids"] == [201]
        assert body["owner_user_id"] == store["users"][0]
    else:
        assert body["workspace_id"] == store["ws"][0]
    assert snapshot(store["db"]) == before


def test_owned_update_preserves_allowed_fields_and_existing_status_semantics(store):
    ga_id = store["answer"]()
    body = {
        "question_text": "Changed question",
        "answer_text": "Changed answer",
        "category": "Synthetic",
        "status": "custom_status",
        "confidence": 0.45,
        "review_cycle_days": 0,
        "customer_override_for": "Synthetic customer",
    }
    response = call(store, "update", ga_id, body)
    assert response.status_code == 200
    assert all(response.json()[key] == value for key, value in body.items())
    store["db"].expire_all()
    row = store["db"].get(GoldenAnswer, ga_id)
    assert all(getattr(row, key) == value for key, value in body.items())
    assert row.workspace_id == store["ws"][0]


def test_owned_update_keeps_null_and_omitted_fields(store):
    ga_id = store["answer"]()
    before = snapshot(store["db"])
    for body in ({}, {"answer_text": None, "status": None, "review_cycle_days": None}):
        response = call(store, "update", ga_id, body)
        assert response.status_code == 200
        assert response.json()["answer_text"] == "Synthetic private golden answer"
        assert response.json()["status"] == "pending_review"
        assert response.json()["review_cycle_days"] == 17
        assert snapshot(store["db"]) == before


STATUSES = ("draft", "pending_review", "approved", "rejected", "changes_requested", "expired")


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("cycle", [17, 0, None])
def test_owned_review_preserves_status_and_expiry_behavior(store, status, cycle):
    ga_id = store["answer"](status)
    row = store["db"].get(GoldenAnswer, ga_id)
    row.review_cycle_days = cycle
    store["db"].commit()
    original_events = snapshot(store["db"])["answer_approval_events"]
    response = call(store, "review", ga_id)
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    store["db"].expire_all()
    row = store["db"].get(GoldenAnswer, ga_id)
    assert row.status == "approved" and row.review_cycle_days == cycle
    assert row.last_reviewed_at and row.expires_at
    assert abs((row.expires_at - row.last_reviewed_at).total_seconds() - (cycle or 90) * 86400) < 1
    assert snapshot(store["db"])["answer_approval_events"] == original_events


@pytest.mark.parametrize("status", STATUSES)
def test_owned_reuse_preserves_status_and_increments_persisted_count(store, status):
    ga_id = store["answer"](status)
    original_events = snapshot(store["db"])["answer_approval_events"]
    for count in (1, 2):
        response = call(store, "reuse", ga_id)
        assert response.status_code == 200
        assert response.json()["reuse_count"] == count and response.json()["status"] == status
        store["db"].expire_all()
        row = store["db"].get(GoldenAnswer, ga_id)
        assert row.reuse_count == count and row.status == status
    assert snapshot(store["db"])["answer_approval_events"] == original_events


@pytest.mark.parametrize("action", ["list", "expiring", "similar"])
def test_existing_collection_queries_keep_workspace_scope(store, action):
    own_id, foreign_id = store["answer"]("approved"), store["answer"]("approved", "foreign")
    for ga_id in (own_id, foreign_id):
        store["db"].get(GoldenAnswer, ga_id).expires_at = datetime.now() + timedelta(days=1)
    store["db"].commit()
    before = snapshot(store["db"])
    if action == "similar":
        response = store["client"].post(
            "/api/golden-answers/similar",
            json={"question_text": "Synthetic private golden question"},
        )
    else:
        response = store["client"].get(
            "/api/golden-answers" + ("/expiring" if action == "expiring" else "")
        )
    assert response.status_code == 200
    rows = response.json()["answers" if action == "list" else action]
    assert {row["id"] for row in rows} == {own_id}
    assert snapshot(store["db"]) == before
