"""TC-12-001: real HTTP routing and atomic answer writes with stored authority.

SQLite cases are local controls; the same cases on migrated PostgreSQL are the
required acceptance. Collection creates no connections, sessions or credentials.
"""

import secrets
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.answers import router
from app.core.database import Base, get_db
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

# Exact owned IDs are deleted in FK order, without changing constraints/sequences.
MODELS = (
    Answer,
    Question,
    Questionnaire,
    Document,
    AuditEvent,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
STATUSES = ("draft", "approved", "rejected", "flagged", "pending", "insufficient_evidence")


def snapshot(db):
    db.expire_all()
    return {
        model.__tablename__: {
            row["id"]: dict(row)
            for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
        }
        for model in MODELS
    }


def assert_answer_changes(db, before, *, updates=None, created=None):
    """Compare every column, except the timestamp of an intentionally updated row."""
    after = snapshot(db)
    old_answers = before.pop("answers")
    new_answers = after.pop("answers")
    assert after == before, "Answer mutation changed another domain/authentication row"
    for answer_id, old in old_answers.items():
        new = new_answers.pop(answer_id)
        changed = (updates or {}).get(answer_id)
        if changed is not None:
            old = {**old, **changed}
            assert new["updated_at"] >= old["updated_at"]
            old["updated_at"] = new["updated_at"]
        assert new == old
    assert len(new_answers) == len(created or {})
    assert {row["question_id"] for row in new_answers.values()} == set(created or {})
    for row in new_answers.values():
        assert row["created_at"] and row["updated_at"]
        expected = {
            column.name: None
            for column in Answer.__table__.columns
            if column.name not in {"id", "created_at", "updated_at"}
        }
        expected.update(question_id=row["question_id"], **created[row["question_id"]])
        assert {key: row[key] for key in expected} == expected


@pytest.fixture(
    params=(
        pytest.param("sqlite", marks=pytest.mark.unit),
        pytest.param("postgres", marks=pytest.mark.integration),
    )
)
def answers_authority(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        from app.core.database import SessionLocal

        db = SessionLocal()
        engine = None
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        Base.metadata.create_all(engine, tables=[model.__table__ for model in MODELS])
        db = Session(engine)
    baseline = snapshot(db)
    owned = {model: [] for model in MODELS}

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        suffix = secrets.token_hex(8)
        first = db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM workspaces")).scalar_one()
        ws = add(Workspace, id=first, name="Answers A", slug=f"answers-a-{suffix}")
        other = add(Workspace, id=first + 1, name="Answers B", slug=f"answers-b-{suffix}")
        user = add(
            User,
            email=f"answers-{suffix}@example.com",
            password_hash="synthetic-unused",
            email_verified=True,
        )
        member = add(WorkspaceMember, workspace_id=ws.id, user_id=user.id, role="admin")
        add(CustomRole, workspace_id=ws.id, name="no-review", can_review=False)
        sid = secrets.token_hex(24)
        session_row = add(UserSession, user_id=user.id, session_id=sid)
        qnrs = {}
        questions = {}
        answers = {}
        for name in ("existing", "new", "untouched", "foreign", "deleted"):
            qnr = add(
                Questionnaire,
                workspace_id=other.id if name == "foreign" else ws.id,
                filename=f"{name}.xlsx",
                status="parsed",
                deleted_at=datetime(2026, 1, 1) if name == "deleted" else None,
            )
            question = add(Question, questionnaire_id=qnr.id, text=f"{name} question")
            qnrs[name] = qnr.id
            questions[name] = question.id
            if name != "new":
                answer = add(
                    Answer,
                    question_id=question.id,
                    text=f"{name} answer",
                    status="draft",
                    confidence=73,
                    citations='[{"text":"synthetic citation"}]',
                    insufficient_reason="synthetic reason",
                    gating_reason="no_evidence",
                    primary_categories_json='{"subjects":["synthetic"]}',
                    evidence_fingerprint="synthetic-fingerprint",
                    outcome_code="answered",
                )
                answers[name] = answer.id
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        # All signing, session, membership and permission logic is real.
        app.dependency_overrides[get_db] = lambda: db

        @contextmanager
        def client(role="admin"):
            if role is not None:
                member.role = role
                db.commit()
            with TestClient(app, follow_redirects=False) as http:
                if role is not None:
                    http.cookies.set(
                        "tc_session",
                        sign_session(
                            user.id,
                            user.email,
                            workspace_id=ws.id,
                            role=role,
                            session_id=sid,
                            max_age_seconds=3600,
                        ),
                    )
                yield http

        yield {
            "db": db,
            "client": client,
            "questions": questions,
            "answers": answers,
            "qnrs": qnrs,
            "other_ws": other.id,
            "member": member.id,
            "session": session_row.id,
        }
    finally:
        try:
            db.rollback()
            # Request-created answers belong only to this fixture's exact question
            # IDs. Capture their exact IDs; never delete by a global ID watermark.
            owned[Answer] = list(
                db.scalars(select(Answer.id).where(Answer.question_id.in_(owned[Question])))
            )
            for model in MODELS:
                if owned[model]:
                    db.query(model).filter(model.id.in_(owned[model])).delete(
                        synchronize_session=False
                    )
            db.commit()
            assert snapshot(db) == baseline, "Fixture did not restore every original full row"
        finally:
            db.close()
            if engine is not None:
                engine.dispose()


@pytest.mark.parametrize("slash", ("", "/"))
@pytest.mark.parametrize("role", ("admin", "editor", "reviewer"))
def test_first_answer_both_post_paths_without_redirect(answers_authority, slash, role):
    f = answers_authority
    qid = f["questions"]["new"]
    with f["client"](role) as client:
        before = snapshot(f["db"])
        response = client.post(f"/api/answers{slash}", json={"question_id": qid})
    assert response.status_code == 200, response.text
    assert not response.history and "location" not in response.headers
    row = f["db"].query(Answer).filter(Answer.question_id == qid).one()
    assert response.json() == {"id": row.id, "question_id": qid, "text": "", "status": "draft"}
    assert_answer_changes(f["db"], before, created={qid: {"text": "", "status": "draft"}})


@pytest.mark.parametrize("slash", ("", "/"))
def test_existing_upsert_preserves_fields_and_empty_text_contract(answers_authority, slash):
    f = answers_authority
    qid, aid = f["questions"]["existing"], f["answers"]["existing"]
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.post(
            f"/api/answers{slash}",
            json={"question_id": qid, "text": "Human replacement", "status": "approved"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "id": aid,
            "question_id": qid,
            "text": "Human replacement",
            "status": "approved",
        }
        assert_answer_changes(
            f["db"],
            before,
            updates={
                aid: {"text": "Human replacement", "status": "approved", "outcome_code": None}
            },
        )
        before = snapshot(f["db"])
        response = client.post(
            f"/api/answers{slash}", json={"question_id": qid, "text": "", "status": "pending"}
        )
        assert response.status_code == 200
        assert response.json() == {
            "id": aid,
            "question_id": qid,
            "text": "Human replacement",
            "status": "pending",
        }
        assert_answer_changes(f["db"], before, updates={aid: {"status": "pending"}})


def test_dynamic_update_still_reaches_individual_handler(answers_authority):
    f = answers_authority
    aid = f["answers"]["existing"]
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch(f"/api/answers/{aid}", json={"text": "", "status": "flagged"})
    assert response.status_code == 200
    assert response.json() == {
        "id": aid,
        "question_id": f["questions"]["existing"],
        "text": "",
        "status": "flagged",
    }
    assert_answer_changes(
        f["db"], before, updates={aid: {"text": "", "status": "flagged", "outcome_code": None}}
    )


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", ("admin", "editor", "reviewer"))
def test_bulk_creates_and_updates_unique_authorized_questions(answers_authority, status, role):
    f = answers_authority
    existing, new = f["questions"]["existing"], f["questions"]["new"]
    with f["client"](role) as client:
        before = snapshot(f["db"])
        response = client.patch(
            "/api/answers/bulk", json={"question_ids": [existing, new], "status": status}
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"updated": 2, "status": status}
        assert_answer_changes(
            f["db"],
            before,
            updates={f["answers"]["existing"]: {"status": status}},
            created={new: {"text": "", "status": status}},
        )
        # Retrying must not create duplicate answer rows or alter unrelated fields.
        before = snapshot(f["db"])
        repeated = client.patch(
            "/api/answers/bulk", json={"question_ids": [new, existing], "status": status}
        )
        assert repeated.status_code == 200 and repeated.json() == response.json()
        assert snapshot(f["db"]) == before


@pytest.mark.parametrize(
    "kind",
    (
        "empty",
        "duplicate-existing",
        "duplicate-new",
        "zero",
        "negative",
        "overflow",
        "bool",
        "string",
        "float",
        "null",
        "null-list",
        "missing-list",
        "invalid-status",
        "empty-status",
    ),
)
def test_bulk_invalid_request_is_unchanged(answers_authority, kind):
    f = answers_authority
    qid = f["questions"]["existing"]
    body = {"question_ids": [qid], "status": "approved"}
    invalid_ids = {
        "zero": 0,
        "negative": -1,
        "overflow": 2147483648,
        "bool": True,
        "string": str(qid),
        "float": float(qid),
        "null": None,
    }
    expected = 400
    if kind in invalid_ids:
        body["question_ids"].append(invalid_ids[kind])
        if kind in {"bool", "string", "float", "null"}:
            expected = 422
    elif kind == "empty":
        body["question_ids"] = []
    elif kind.startswith("duplicate-"):
        repeated = f["questions"][kind.removeprefix("duplicate-")]
        body["question_ids"] = [repeated, repeated]
    elif kind == "null-list":
        body["question_ids"] = None
        expected = 422
    elif kind == "missing-list":
        del body["question_ids"]
        expected = 422
    else:
        body["status"] = "" if kind == "empty-status" else "unknown"
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch("/api/answers/bulk", json=body)
        assert snapshot(f["db"]) == before
    assert response.status_code == expected, response.text
    if expected == 422:
        assert all(error["loc"][0] == "body" for error in response.json()["detail"])
    else:
        assert response.json() == {"detail": "Invalid request"}


@pytest.mark.parametrize("unavailable", ("foreign", "missing", "deleted", "moved", "removed"))
@pytest.mark.parametrize("unavailable_first", (False, True))
def test_bulk_unavailable_question_is_neutral_and_atomic(
    answers_authority, unavailable, unavailable_first
):
    f = answers_authority
    if unavailable == "moved":
        f["db"].get(Questionnaire, f["qnrs"]["untouched"]).workspace_id = f["other_ws"]
        f["db"].commit()
        target = f["questions"]["untouched"]
    elif unavailable == "removed":
        f["db"].delete(f["db"].get(Questionnaire, f["qnrs"]["untouched"]))
        f["db"].commit()  # Real FK cascade removes its question/answer.
        target = f["questions"]["untouched"]
    else:
        target = 2147483647 if unavailable == "missing" else f["questions"][unavailable]
    ids = [f["questions"]["existing"], f["questions"]["new"], target]
    if unavailable_first:
        ids.reverse()
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch(
            "/api/answers/bulk", json={"question_ids": ids, "status": "approved"}
        )
        assert snapshot(f["db"]) == before
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Question not found"}


@pytest.mark.parametrize("route", ("post", "post-slash", "bulk", "individual"))
@pytest.mark.parametrize("denial", ("anonymous", "permission", "revoked-session", "removed-member"))
def test_every_write_uses_current_stored_authority(answers_authority, route, denial):
    f = answers_authority
    role = None if denial == "anonymous" else "admin"
    expected = 401 if denial in {"anonymous", "revoked-session"} else 403
    with f["client"](role) as client:
        # Downgrade after signing an admin cookie: current stored authority wins.
        if denial == "permission":
            f["db"].get(WorkspaceMember, f["member"]).role = "no-review"
        elif denial == "revoked-session":
            f["db"].delete(f["db"].get(UserSession, f["session"]))
        elif denial == "removed-member":
            f["db"].delete(f["db"].get(WorkspaceMember, f["member"]))
        f["db"].commit()
        before = snapshot(f["db"])
        if route.startswith("post"):
            response = client.post(
                "/api/answers/" if route == "post-slash" else "/api/answers",
                json={"question_id": f["questions"]["new"], "text": "Denied"},
            )
        elif route == "bulk":
            response = client.patch(
                "/api/answers/bulk",
                json={
                    "question_ids": [f["questions"]["existing"], f["questions"]["new"]],
                    "status": "approved",
                },
            )
        else:
            response = client.patch(
                f"/api/answers/{f['answers']['existing']}", json={"text": "Denied"}
            )
        assert snapshot(f["db"]) == before
    assert response.status_code == expected, response.text
