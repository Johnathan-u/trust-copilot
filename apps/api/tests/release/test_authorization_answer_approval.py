"""Golden-answer approval authorization with actual stored auth and FK-enforced data.

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

from app.api.routes.answer_approval import router
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
OBJECT_ACTIONS = (
    "assign-owner",
    "assign-reviewer",
    "submit",
    "approve",
    "reject",
    "request-changes",
    "history",
    "bulk-approve",
)
ALL_ACTIONS = (*OBJECT_ACTIONS, "queue", "overdue")
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
                question_text="Synthetic private approval question",
                answer_text="Synthetic private approval answer",
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


def call(store, action, ga_id=None, *, assignee=None, bulk=None):
    if action in ("queue", "overdue"):
        return store["client"].get(f"/api/answer-approval/{action}")
    if action == "history":
        return store["client"].get(f"/api/answer-approval/{ga_id}/history")
    if action.startswith("assign-"):
        return store["client"].post(
            f"/api/answer-approval/{action}",
            json={
                "golden_answer_id": ga_id,
                "user_id": store["users"][1] if assignee is None else assignee,
            },
        )
    if action == "bulk-approve":
        return store["client"].post(
            "/api/answer-approval/bulk-approve",
            json={
                "golden_answer_ids": [ga_id] if bulk is None else bulk,
            },
        )
    return store["client"].post(
        f"/api/answer-approval/{ga_id}/{action}", json={"comment": "Synthetic review comment"}
    )


def deny_without_writes(store, action, ga_id=None, status=404, **kwargs):
    db = store["db"]
    before = snapshot(db)
    writes = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(store["engine"], "before_cursor_execute", capture)
    try:
        response = call(store, action, ga_id, **kwargs)
    finally:
        event.remove(store["engine"], "before_cursor_execute", capture)
    assert response.status_code == status, response.text
    if status == 404:
        assert response.json() == {"detail": "Not Found"}
    assert not writes, "Authorization must precede writes, even writes later rolled back"
    assert not db.new and not db.dirty and not db.deleted
    assert snapshot(db) == before


@pytest.mark.parametrize("action", OBJECT_ACTIONS)
@pytest.mark.parametrize("target", UNAVAILABLE)
def test_unavailable_parent_is_neutral_404_before_any_write(store, action, target):
    ga_id = store["answer"]("draft" if action == "submit" else "pending_review", target)
    deny_without_writes(store, action, ga_id)


@pytest.mark.parametrize("action", ["submit", "approve", "reject", "request-changes"])
def test_foreign_parent_is_denied_before_status_disclosure(store, action):
    ga_id = store["answer"]("approved", "foreign")
    deny_without_writes(store, action, ga_id)


@pytest.mark.parametrize("action", ["assign-owner", "assign-reviewer"])
@pytest.mark.parametrize("target", ["foreign", "suspended", "removed", "missing"])
def test_assignment_requires_current_active_workspace_member(store, action, target):
    user_id = store["users"][1]
    if target == "foreign":
        user_id = store["users"][2]
    elif target == "suspended":
        store["assignee"].suspended = True
    elif target == "removed":
        store["db"].delete(store["assignee"])
    else:
        user_id = 2147483647
    store["db"].commit()
    ga_id = store["answer"]()
    deny_without_writes(store, action, ga_id, assignee=user_id)


@pytest.mark.parametrize("target", UNAVAILABLE)
@pytest.mark.parametrize("foreign_first", [False, True])
def test_bulk_preflights_every_parent_before_any_write(store, target, foreign_first):
    own_id, bad_id = store["answer"](), store["answer"](target=target)
    batch = [bad_id, own_id] if foreign_first else [own_id, bad_id]
    deny_without_writes(store, "bulk-approve", bulk=batch)


@pytest.mark.parametrize("role", ["admin", "editor", "reviewer", "session_only"])
@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_existing_route_permissions_follow_current_membership(store, role, action):
    store["actor"].role = role  # Cookie still says admin; current stored authority must win.
    store["db"].commit()
    ga_id = store["answer"]("draft" if action == "submit" else "pending_review")
    admin_only = action in ("assign-owner", "assign-reviewer", "overdue")
    review_only = action in ("approve", "reject", "request-changes", "bulk-approve")
    allowed = (not admin_only or role == "admin") and (not review_only or role != "session_only")
    if allowed:
        response = call(store, action, ga_id)
        assert response.status_code == 200, response.text
    else:
        deny_without_writes(store, action, ga_id, status=403)


@pytest.mark.parametrize("action", ["history", "approve", "assign-owner"])
@pytest.mark.parametrize("revocation", ["suspended", "membership_removed", "session_removed"])
def test_stale_authority_is_denied_without_writes(store, action, revocation):
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


def events(store, ga_id):
    store["db"].expire_all()
    return list(
        store["db"].scalars(
            select(AnswerApprovalEvent)
            .where(AnswerApprovalEvent.golden_answer_id == ga_id)
            .order_by(AnswerApprovalEvent.id)
        )
    )


def test_authorized_submit_approve_preserves_fields_events_and_cycle(store):
    ga_id = store["answer"]("draft")
    response = call(store, "submit", ga_id)
    assert response.status_code == 200
    assert response.json()["status"] == "pending_review"
    assert response.json()["submitted_at"]
    response = call(store, "approve", ga_id)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved" and body["workspace_id"] == store["ws"][0]
    assert body["question_text"] == "Synthetic private approval question"
    assert body["answer_text"] == "Synthetic private approval answer"
    cycle = datetime.fromisoformat(body["expires_at"]) - datetime.fromisoformat(
        body["last_reviewed_at"]
    )
    assert abs(cycle.total_seconds() - 17 * 86400) < 1
    rows = events(store, ga_id)
    assert [row.action for row in rows] == ["submitted", "submitted", "approved"]
    assert rows[-1].actor_user_id == store["users"][0]
    assert rows[-1].comment == "Synthetic review comment"
    persisted = store["db"].get(GoldenAnswer, ga_id)
    assert persisted.status == "approved" and persisted.review_cycle_days == 17
    assert persisted.last_reviewed_at and persisted.expires_at
    deny_without_writes(store, "approve", ga_id, status=400)


def test_authorized_change_request_resubmit_and_reject(store):
    ga_id = store["answer"]()
    for action, status in (
        ("request-changes", "changes_requested"),
        ("submit", "pending_review"),
        ("reject", "rejected"),
    ):
        response = call(store, action, ga_id)
        assert response.status_code == 200 and response.json()["status"] == status
    assert [row.action for row in events(store, ga_id)] == [
        "submitted",
        "changes_requested",
        "submitted",
        "rejected",
    ]
    deny_without_writes(store, "submit", ga_id, status=400)


def test_authorized_assignment_has_no_new_recipient_role_restriction(store):
    ga_id = store["answer"]()
    for role in ("admin", "editor", "reviewer", "session_only"):
        store["assignee"].role = role
        store["db"].commit()
        for action, field in (
            ("assign-owner", "owner_user_id"),
            ("assign-reviewer", "reviewer_user_id"),
        ):
            response = call(store, action, ga_id)
            assert response.status_code == 200 and response.json()[field] == store["users"][1]
    assert [row.action for row in events(store, ga_id)][1:] == [
        "owner_assigned",
        "reviewer_assigned",
    ] * 4


def test_authorized_bulk_preserves_status_skips_duplicates_and_empty_input(store):
    pending = store["answer"]()
    skipped = [
        store["answer"](status)
        for status in ("draft", "approved", "rejected", "changes_requested", "expired")
    ]
    before = {ga_id: len(events(store, ga_id)) for ga_id in [pending, *skipped]}
    skipped_rows = list(
        store["db"].execute(
            select(GoldenAnswer.__table__)
            .where(GoldenAnswer.id.in_(skipped))
            .order_by(GoldenAnswer.id)
        )
    )
    response = call(store, "bulk-approve", bulk=[pending, *skipped, pending])
    assert response.status_code == 200
    assert response.json() == {"approved": [pending], "skipped": [*skipped, pending]}
    assert len(events(store, pending)) == before[pending] + 1
    assert all(len(events(store, ga_id)) == before[ga_id] for ga_id in skipped)
    assert (
        list(
            store["db"].execute(
                select(GoldenAnswer.__table__)
                .where(GoldenAnswer.id.in_(skipped))
                .order_by(GoldenAnswer.id)
            )
        )
        == skipped_rows
    )
    original = snapshot(store["db"])
    assert call(store, "bulk-approve", bulk=[]).json() == {"approved": [], "skipped": []}
    assert snapshot(store["db"]) == original


def test_queue_overdue_and_history_keep_own_positive_controls(store):
    own_id, foreign_id = store["answer"](), store["answer"](target="foreign")
    before = snapshot(store["db"])
    for action, key in (("queue", "queue"), ("overdue", "overdue")):
        response = call(store, action)
        assert response.status_code == 200
        returned = {row["id"] for row in response.json()[key]}
        assert own_id in returned and foreign_id not in returned
    response = call(store, "history", own_id)
    assert response.status_code == 200
    assert response.json()["events"][0]["comment"] == "Synthetic existing approval comment"
    assert snapshot(store["db"]) == before
    store["db"].query(AnswerApprovalEvent).filter_by(golden_answer_id=own_id).delete(
        synchronize_session=False
    )
    store["db"].commit()
    before = snapshot(store["db"])
    response = call(store, "history", own_id)
    assert response.status_code == 200 and response.json() == {"events": []}
    assert snapshot(store["db"]) == before
