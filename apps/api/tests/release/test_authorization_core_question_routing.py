"""Current questionnaire authority for confidence reads, with real stored auth."""

import hashlib
import json
import secrets
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes.confidence_routing import router
from app.core.database import get_db
from app.core.session import sign_session
from app.models import (
    Answer,
    ApiKey,
    AuditEvent,
    CustomRole,
    Document,
    Question,
    Questionnaire,
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
    CustomRole,
    ApiKey,
    Document,
    Questionnaire,
    Question,
    Answer,
    AuditEvent,
)
MISSING = 2147483647
NOT_FOUND = {"detail": "Referenced resource not found"}


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
def routing(request):
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
    owned = {model: [] for model in MODELS}
    token = secrets.token_hex(8)
    client = None

    def add(model, **values):
        row = model(**values)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        workspaces = []
        for label in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if db.get(Workspace, wid) is None:
                    break
            workspaces.append(add(Workspace, id=wid, name=label, slug=f"routing-{label}-{token}"))
        own, foreign = workspaces
        user = add(User, email=f"routing-{token}@example.com", password_hash="synthetic-unused")
        member = add(WorkspaceMember, user_id=user.id, workspace_id=own.id, role="reviewer")
        sid = f"routing-{token}"
        add(UserSession, user_id=user.id, session_id=sid)
        add(
            CustomRole,
            workspace_id=own.id,
            name="no-flags",
            can_edit=False,
            can_review=False,
            can_export=False,
            can_admin=False,
        )
        qnr = add(Questionnaire, workspace_id=own.id, filename="own-synthetic.xlsx")
        other = add(Questionnaire, workspace_id=foreign.id, filename="foreign-synthetic.xlsx")
        questions, expected = {}, {}
        for label, parent, confidence in (
            ("low", qnr, 20),
            ("medium", qnr, 55),
            ("high", qnr, 90),
            ("unanswered", qnr, None),
            ("foreign", other, 20),
        ):
            question = add(Question, questionnaire_id=parent.id, text=f"Synthetic {label} question")
            questions[label] = question.id
            if confidence is None:
                expected[label] = {
                    "question_id": question.id,
                    "route": "human_review",
                    "confidence": None,
                    "reasons": ["No answer generated yet"],
                }
                continue
            answer = add(
                Answer,
                question_id=question.id,
                text="Synthetic answer",
                status="draft",
                confidence=confidence,
                gating_reason="PRIVATE-foreign" if label == "foreign" else None,
            )
            route = {20: "human_review", 55: "review_suggested", 90: "auto_draft"}[confidence]
            reasons = {
                20: ["Low confidence (20%); requires human review"],
                55: ["Moderate confidence; human review recommended"],
                90: [],
            }[confidence]
            expected[label] = {
                "question_id": question.id,
                "answer_id": answer.id,
                "route": route,
                "confidence": confidence,
                "answer_status": "draft",
                "reasons": reasons,
            }
        db.commit()
        assert db.get(Question, MISSING) is None and db.get(Questionnaire, MISSING) is None
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        app.dependency_overrides[get_db] = database
        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set(
            "tc_session",
            sign_session(user.id, user.email, own.id, "admin", sid, max_age_seconds=3600),
        )
        yield {
            "db": db,
            "client": client,
            "member": member,
            "user": user,
            "sid": sid,
            "workspace": own.id,
            "foreign_workspace": foreign.id,
            "qnr": qnr,
            "qnr_id": qnr.id,
            "foreign_qnr_id": other.id,
            "questions": questions,
            "expected": expected,
        }
    finally:
        if client is not None:
            client.close()
        db.rollback()
        for model in reversed(MODELS):
            if owned[model]:
                db.query(model).filter(model.id.in_(owned[model])).delete(synchronize_session=False)
        db.commit()
        assert snapshot(db) == baseline, "Owned cleanup changed pre-existing full rows"
        assert _safety.blocked_attempts() == outbound_before
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def read(state, surface, *, question_id=None, questionnaire_id=None, ids=None, expected=200):
    db = state["db"]
    before = snapshot(db)
    statements = []

    def record_sql(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record_sql)
    try:
        if surface == "batch":
            response = state["client"].post(
                "/api/confidence-routing/batch",
                json={"question_ids": ids if ids is not None else [state["questions"]["low"]]},
            )
        elif surface == "queue":
            response = state["client"].get(
                f"/api/confidence-routing/queue/{questionnaire_id or state['qnr_id']}"
            )
        else:
            response = state["client"].get(
                f"/api/confidence-routing/question/{question_id or state['questions']['low']}"
            )
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record_sql)
    db.expire_all()
    assert response.status_code == expected, response.text
    assert snapshot(db) == before, "Read changed full rows"
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements), statements
    if expected == 404:
        assert response.json() == NOT_FOUND
        assert not any(
            "FROM answers" in sql for sql in statements
        ), "Projection ran before all parents were authorized"
        assert "PRIVATE" not in response.text
    return response


@pytest.mark.parametrize("label", ("low", "medium", "high", "unanswered"))
def test_owned_question_preserves_existing_routing_projection(routing, label):
    assert (
        read(routing, "question", question_id=routing["questions"][label]).json()
        == routing["expected"][label]
    )


def test_owned_queue_preserves_review_selection_and_details(routing):
    body = read(routing, "queue").json()
    assert {item["question_id"]: item for item in body["queue"]} == {
        routing["questions"][label]: routing["expected"][label]
        for label in ("low", "medium", "unanswered")
    }


@pytest.mark.parametrize("labels", ([], ["high", "low", "low", "medium", "unanswered"]))
def test_owned_batch_preserves_empty_duplicates_and_counts(routing, labels):
    body = read(routing, "batch", ids=[routing["questions"][label] for label in labels]).json()
    expected = {"auto_draft": [], "review_suggested": [], "human_review": []}
    for label in labels:
        item = routing["expected"][label]
        expected[item["route"]].append(item)
    assert body == {
        "total": len(labels),
        "auto_draft_count": len(expected["auto_draft"]),
        "review_suggested_count": len(expected["review_suggested"]),
        "human_review_count": len(expected["human_review"]),
        "details": expected,
    }


@pytest.mark.parametrize("surface", ("question", "queue", "batch"))
@pytest.mark.parametrize("parent", ("foreign", "moved", "archived", "deleted", "missing"))
def test_current_parent_is_required_before_any_projection(routing, surface, parent):
    state = routing
    qid, qnr_id = state["questions"]["low"], state["qnr_id"]
    if parent == "foreign":
        qid, qnr_id = state["questions"]["foreign"], state["foreign_qnr_id"]
    elif parent == "moved":
        state["qnr"].workspace_id = state["foreign_workspace"]
    elif parent == "archived":
        state["qnr"].deleted_at = datetime(2026, 1, 3)
    elif parent == "deleted":
        state["db"].delete(state["qnr"])
    else:
        qid = qnr_id = MISSING
    state["db"].commit()
    read(
        state,
        surface,
        question_id=qid,
        questionnaire_id=qnr_id,
        ids=[state["questions"]["high"], qid],
        expected=404,
    )


@pytest.mark.parametrize("surface", ("question", "batch"))
def test_reparented_question_cannot_keep_its_old_workspace_authority(routing, surface):
    state = routing
    state["db"].get(Question, state["questions"]["low"]).questionnaire_id = state["foreign_qnr_id"]
    state["db"].commit()
    read(state, surface, expected=404)


@pytest.mark.parametrize("surface", ("question", "queue", "batch"))
@pytest.mark.parametrize(
    "denial,status",
    (("anonymous", 401), ("expired", 401), ("revoked", 401), ("suspended", 403), ("removed", 403)),
)
def test_current_stored_principal_is_required(routing, surface, denial, status):
    state = routing
    read(state, surface)
    if denial == "anonymous":
        state["client"].cookies.clear()
    elif denial == "expired":
        state["client"].cookies.set(
            "tc_session",
            sign_session(
                state["user"].id,
                state["user"].email,
                state["workspace"],
                "admin",
                state["sid"],
                max_age_seconds=-1,
            ),
        )
    elif denial == "revoked":
        state["db"].query(UserSession).filter_by(session_id=state["sid"]).delete()
    elif denial == "suspended":
        state["member"].suspended = True
    else:
        state["db"].delete(state["member"])
    state["db"].commit()
    assert "answer_id" not in read(state, surface, expected=status).text


@pytest.mark.parametrize("surface", ("question", "queue", "batch"))
def test_existing_session_only_permission_is_preserved(routing, surface):
    expected = read(routing, surface).json()
    routing["member"].role = "no-flags"
    routing["db"].commit()
    assert read(routing, surface).json() == expected


@pytest.mark.parametrize("surface", ("question", "queue", "batch"))
def test_existing_request_validation_is_preserved(routing, surface):
    read(
        routing, surface, question_id="invalid", questionnaire_id="invalid", ids=[{}], expected=422
    )


def test_parent_lookup_failure_does_not_fall_through_to_batch_projection(routing):
    engine = routing["db"].get_bind()

    def fail_lookup(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM questions JOIN questionnaires" in statement and "WHERE" in statement:
            raise RuntimeError("Synthetic parent lookup failure")

    event.listen(engine, "before_cursor_execute", fail_lookup)
    try:
        assert "answer_id" not in read(routing, "batch", expected=500).text
    finally:
        event.remove(engine, "before_cursor_execute", fail_lookup)
