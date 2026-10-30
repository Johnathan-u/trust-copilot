"""TC-06-003h: existing widget reads use current stored workspace authority.

Acceptance only: preserve the current counters, including archived rows. Broader
counter/state correctness remains TC-23-005. No providers or storage are used.
"""

import hashlib
import json
import secrets
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import proof_widgets
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    Answer,
    ApiKey,
    AuditEvent,
    CustomRole,
    Document,
    Job,
    Question,
    Questionnaire,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.models.export_record import ExportRecord

MODELS = (
    ExportRecord,
    Answer,
    Question,
    Questionnaire,
    Document,
    Job,
    AuditEvent,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
PATH = "/api/proof-widgets"
OWN = (1, 1, 1, 1, 50.0)
FOREIGN = (2, 2, 2, 2, 66.7)


def snapshot(store):
    result = {}
    for model in MODELS:
        rows = [
            list(row) for row in store["db"].execute(select(model.__table__).order_by(model.id))
        ]
        result[model.__tablename__] = (
            len(rows),
            hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest(),
        )
    return result


@pytest.fixture(
    params=(
        pytest.param("sqlite", marks=pytest.mark.unit),
        pytest.param("postgres", marks=pytest.mark.integration),
    )
)
def widget_store(request):
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
    store = {"db": db, "engine": engine}
    original = snapshot(store)
    owned = {model: set() for model in MODELS}
    clients = []

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].add(row.id)
        return row

    def remember(current, _context):
        for row in current.new:
            if type(row) in owned:
                owned[type(row)].add(row.id)

    try:
        suffix = secrets.token_hex(8)
        first_ws = int(db.scalar(select(func.max(Workspace.id))) or 0) + 1
        ws = [
            add(Workspace, id=first_ws + i, name="Widgets", slug=f"widgets-{suffix}-{i}").id
            for i in range(2)
        ]
        users = [
            add(User, email=f"widgets-{suffix}-{i}@example.com", password_hash="unused")
            for i in range(2)
        ]
        members = [
            add(WorkspaceMember, workspace_id=ws[i], user_id=users[i].id, role="admin")
            for i in range(2)
        ]
        add(
            CustomRole,
            workspace_id=ws[0],
            name="session_only",
            can_review=False,
            can_edit=False,
            can_admin=False,
            can_export=False,
        )
        sids = [secrets.token_hex(24) for _ in range(2)]
        sessions = [add(UserSession, user_id=users[i].id, session_id=sids[i]) for i in range(2)]
        sources = []
        for index in range(2):
            qnrs = [
                add(Questionnaire, workspace_id=ws[index], filename=f"widgets-{j}.xlsx")
                for j in range(index + 1)
            ]
            questions = [
                add(Question, questionnaire_id=qnrs[0].id, text=f"Synthetic question {j}")
                for j in range(index + 2)
            ]
            answers = [
                add(Answer, question_id=questions[j].id, text="Synthetic answer")
                for j in range(index + 1)
            ]
            documents = [
                add(
                    Document,
                    workspace_id=ws[index],
                    storage_key=f"synthetic/{suffix}/{index}/doc-{j}",
                    filename=f"doc-{j}.txt",
                )
                for j in range(index + 1)
            ]
            # Nullable links deliberately stay null: these independent records can
            # move without violating the real PostgreSQL same-workspace triggers.
            exports = [
                add(
                    ExportRecord,
                    workspace_id=ws[index],
                    storage_key=f"synthetic/{suffix}/{index}/export-{j}",
                    filename=f"export-{j}.xlsx",
                )
                for j in range(index + 1)
            ]
            sources.append(
                dict(
                    questionnaires=qnrs,
                    questions=questions,
                    answers=answers,
                    documents=documents,
                    exports=exports,
                )
            )
        db.commit()
        app = FastAPI()
        app.include_router(proof_widgets.router, prefix="/api")

        def database():
            with Session(engine) as current:
                event.listen(current, "after_flush", remember)
                yield current

        app.dependency_overrides[get_db] = database
        for index in range(2):
            client = TestClient(app)
            clients.append(client)
            client.cookies.set(
                "tc_session",
                sign_session(
                    users[index].id,
                    users[index].email,
                    ws[index],
                    "admin",
                    session_id=sids[index],
                    max_age_seconds=3600,
                ),
            )
        store.update(
            clients=clients,
            ws=ws,
            users=users,
            members=members,
            sessions=sessions,
            sources=sources,
            add=add,
        )
        yield store
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
            assert snapshot(store) == original
        finally:
            db.close()
            if request.param == "sqlite":
                engine.dispose()


def read(store, expected=OWN, *, index=0, status=200, detail=None, path=PATH):
    before = snapshot(store)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(store["engine"], "before_cursor_execute", capture)
    try:
        response = store["clients"][index].get(path)
    finally:
        event.remove(store["engine"], "before_cursor_execute", capture)
    assert response.status_code == status
    assert set(statements) <= {"SELECT"}, "Widget reads must execute SELECT only"
    assert snapshot(store) == before
    if status != 200:
        assert response.json() == {"detail": detail}
        return
    assert statements, "Successful widget reads must query the real store"
    data = response.json()
    generated = datetime.fromisoformat(data.pop("generated_at"))
    assert generated.tzinfo is not None
    answers, questionnaires, documents, exports, coverage = expected
    assert data == {
        "questions_answered": answers,
        "questionnaires_processed": questionnaires,
        "documents_indexed": documents,
        "exports_delivered": exports,
        "hours_saved_estimate": round(answers * 0.08, 1),
        "hours_saved_basis": "heuristic: 0.08 hours (about 5 minutes) assumed per answer; not measured",
        "coverage_pct": coverage,
    }


@pytest.mark.parametrize("index,expected", [(0, OWN), (1, FOREIGN)])
def test_each_current_tenant_receives_only_its_existing_counts(widget_store, index, expected):
    read(widget_store, expected, index=index)


@pytest.mark.parametrize("kind", ["questionnaires", "questions", "answers", "documents", "exports"])
def test_foreign_row_deletion_does_not_change_own_widgets(widget_store, kind):
    s = widget_store
    read(s)
    s["db"].delete(s["sources"][1][kind][0])
    s["db"].commit()
    read(s)


@pytest.mark.parametrize(
    "kind,own_after,foreign_after",
    [
        ("questionnaires", (0, 0, 1, 1, 0), (3, 3, 2, 2, 60.0)),
        ("documents", (1, 1, 0, 1, 50.0), (2, 2, 3, 2, 66.7)),
        ("exports", (1, 1, 1, 0, 50.0), (2, 2, 2, 3, 66.7)),
    ],
)
def test_current_ownership_follows_valid_moves_in_both_directions(
    widget_store, kind, own_after, foreign_after
):
    s = widget_store
    row = s["sources"][0][kind][0]
    read(s)
    read(s, FOREIGN, index=1)
    row.workspace_id = s["ws"][1]
    s["db"].commit()
    read(s, own_after)
    read(s, foreign_after, index=1)
    row.workspace_id = s["ws"][0]
    s["db"].commit()
    read(s)
    read(s, FOREIGN, index=1)


def test_answer_count_follows_questions_current_questionnaire(widget_store):
    s = widget_store
    s["sources"][0]["questions"][0].questionnaire_id = s["sources"][1]["questionnaires"][0].id
    s["db"].commit()
    read(s, (0, 1, 1, 1, 0))
    read(s, (3, 2, 2, 2, 75.0), index=1)


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("questionnaires", (0, 0, 1, 1, 0)),
        ("questions", (0, 1, 1, 1, 0)),
        ("answers", (0, 1, 1, 1, 0)),
        ("documents", (1, 1, 0, 1, 50.0)),
        ("exports", (1, 1, 1, 0, 50.0)),
    ],
)
def test_valid_deletions_and_cascades_do_not_reveal_foreign_counts(widget_store, kind, expected):
    s = widget_store
    row = s["sources"][0][kind][0]
    model, row_id = type(row), row.id
    answer_id = s["sources"][0]["answers"][0].id
    s["db"].delete(row)
    s["db"].commit()
    s["db"].expire_all()
    assert s["db"].get(model, row_id) is None
    if kind in {"questionnaires", "questions"}:
        assert s["db"].get(Answer, answer_id) is None
    read(s, expected)
    read(s, FOREIGN, index=1)


@pytest.mark.parametrize("kind", ["questionnaires", "documents"])
def test_owned_archived_rows_preserve_existing_count_semantics(widget_store, kind):
    s = widget_store
    s["sources"][0][kind][0].deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    s["db"].commit()
    read(s)


@pytest.mark.parametrize("role", ["admin", "editor", "reviewer", "session_only"])
def test_current_session_only_permission_is_preserved(widget_store, role):
    s = widget_store
    # The existing cookie still says admin; the real dependency resolves this row.
    s["members"][0].role = role
    s["db"].commit()
    read(s)


@pytest.mark.parametrize(
    "state,status,detail",
    [
        ("suspended", 403, "Your account has been suspended in this workspace"),
        ("membership_removed", 403, "Active workspace membership required"),
        ("membership_moved", 403, "Active workspace membership required"),
        ("session_removed", 401, "Session invalidated"),
        ("session_reassigned", 401, "Session invalidated"),
        ("anonymous", 401, "Not authenticated"),
    ],
)
def test_current_authority_loss_denies_without_counts_or_writes(
    widget_store, state, status, detail
):
    s = widget_store
    read(s)
    if state == "suspended":
        s["members"][0].suspended = True
    elif state == "membership_removed":
        s["db"].delete(s["members"][0])
    elif state == "membership_moved":
        s["members"][0].workspace_id = s["ws"][1]
    elif state == "session_removed":
        s["db"].delete(s["sessions"][0])
    elif state == "session_reassigned":
        s["sessions"][0].user_id = s["users"][1].id
    else:
        s["clients"][0].cookies.clear()
    s["db"].commit()
    read(s, status=status, detail=detail)


def test_query_parameter_cannot_select_foreign_workspace(widget_store):
    s = widget_store
    read(s, path=f'{PATH}?workspace_id={s["ws"][1]}')


def test_empty_current_workspace_does_not_fall_back_to_foreign_counts(widget_store):
    s = widget_store
    for kind in ("questionnaires", "documents", "exports"):
        s["db"].delete(s["sources"][0][kind][0])
    s["db"].commit()
    read(s, (0, 0, 0, 0, 0))
    read(s, FOREIGN, index=1)
