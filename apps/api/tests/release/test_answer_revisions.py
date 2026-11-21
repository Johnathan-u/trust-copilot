"""TC-12-002: two editors cannot silently overwrite one answer.

The revision is the answer row's existing ``updated_at``. The editor that
loaded it may save. A second save that still holds that value is 409, and a
later questionnaire read returns the first editor's text.

The fixtures are synthetic. This file does not accept TC-12-002.
"""

from __future__ import annotations

import secrets
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.answers import router as answers_router
from app.api.routes.questionnaires import router as questionnaires_router
from app.core.database import SessionLocal, get_db
from app.core.session import sign_session
from app.models import (
    Answer,
    Question,
    Questionnaire,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
)

ORIGINAL = "Stored answer before either editor saved."
WINNER = "Winner saved this answer."
STALE = "Stale editor tried to replace it."
OMITTED = "This save omitted the loaded revision."


def _revision_token(row: Answer) -> str:
    assert row.updated_at is not None
    return row.updated_at.isoformat()


@pytest.fixture
def two_editors(migrated_db):
    """Two reviewers and a later reader, sharing one workspace and one answer."""
    db = SessionLocal()
    owned: dict[type, list[int]] = {
        Answer: [],
        Question: [],
        Questionnaire: [],
        UserSession: [],
        WorkspaceMember: [],
        User: [],
        Workspace: [],
    }

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    suffix = secrets.token_hex(6)
    first = db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM workspaces")).scalar_one()
    workspace = add(Workspace, id=first, name="Answers rev", slug=f"answers-rev-{suffix}")
    users = {}
    sessions = {}
    for name in ("winner", "stale", "reader"):
        user = add(
            User,
            email=f"answers-rev-{name}-{suffix}@example.com",
            password_hash="synthetic-unused",
            email_verified=True,
        )
        add(WorkspaceMember, workspace_id=workspace.id, user_id=user.id, role="reviewer")
        session_id = secrets.token_hex(16)
        add(UserSession, user_id=user.id, session_id=session_id)
        users[name] = user
        sessions[name] = session_id
    questionnaire = add(
        Questionnaire,
        workspace_id=workspace.id,
        filename="synthetic.xlsx",
        status="parsed",
    )
    question = add(Question, questionnaire_id=questionnaire.id, text="Synthetic question?")
    answer = add(
        Answer,
        question_id=question.id,
        text=ORIGINAL,
        status="draft",
        citations="[]",
        outcome_code="answered",
        insufficient_reason="synthetic reason",
    )
    db.commit()
    db.expire_all()
    loaded = _revision_token(db.get(Answer, answer.id))

    app = FastAPI()
    app.include_router(answers_router, prefix="/api")
    app.include_router(questionnaires_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db

    @contextmanager
    def client(name: str):
        user = users[name]
        with TestClient(app, follow_redirects=False) as http:
            http.cookies.set(
                "tc_session",
                sign_session(
                    user.id,
                    user.email,
                    workspace_id=workspace.id,
                    role="reviewer",
                    session_id=sessions[name],
                    max_age_seconds=3600,
                ),
            )
            yield http

    def read_answer(http: TestClient) -> dict:
        response = http.get(
            f"/api/questionnaires/{questionnaire.id}",
            params={"workspace_id": workspace.id},
        )
        assert response.status_code == 200, response.text
        rows = {item["id"]: item for item in response.json()["questions"]}
        return rows[question.id]["answer"]

    try:
        yield {
            "db": db,
            "client": client,
            "read_answer": read_answer,
            "workspace_id": workspace.id,
            "questionnaire_id": questionnaire.id,
            "question_id": question.id,
            "answer_id": answer.id,
            "loaded": loaded,
        }
    finally:
        db.rollback()
        for model in (
            Answer,
            Question,
            Questionnaire,
            UserSession,
            WorkspaceMember,
            User,
            Workspace,
        ):
            if owned[model]:
                db.query(model).filter(model.id.in_(owned[model])).delete(synchronize_session=False)
        db.commit()
        db.close()


def _stored_text(db: Session, answer_id: int) -> str | None:
    db.expire_all()
    row = db.get(Answer, answer_id)
    assert row is not None
    return row.text


def test_stale_client_gets_409_and_a_later_read_returns_the_winner(two_editors):
    """The second editor still holds the revision both loaded. That save is 409."""
    env = two_editors
    loaded = env["loaded"]
    with env["client"]("winner") as winner:
        saved = winner.patch(
            f"/api/answers/{env['answer_id']}",
            json={"text": WINNER, "updated_at": loaded},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["text"] == WINNER
    with env["client"]("stale") as stale:
        conflict = stale.patch(
            f"/api/answers/{env['answer_id']}",
            json={"text": STALE, "updated_at": loaded},
        )
        assert conflict.status_code == 409, conflict.text
    assert _stored_text(env["db"], env["answer_id"]) == WINNER
    with env["client"]("reader") as reader:
        answer = env["read_answer"](reader)
    assert answer["text"] == WINNER
    assert answer["text"] != STALE
    assert answer["updated_at"] == _revision_token(env["db"].get(Answer, env["answer_id"]))


def test_missing_revision_is_409_and_leaves_the_row(two_editors):
    """A save that does not send the loaded revision does not change the row."""
    env = two_editors
    with env["client"]("winner") as winner:
        rejected = winner.patch(
            f"/api/answers/{env['answer_id']}",
            json={"text": OMITTED},
        )
        assert rejected.status_code == 409, rejected.text
    assert _stored_text(env["db"], env["answer_id"]) == ORIGINAL
    with env["client"]("reader") as reader:
        answer = env["read_answer"](reader)
    assert answer["text"] == ORIGINAL
