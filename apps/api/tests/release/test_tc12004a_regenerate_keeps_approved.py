"""TC-12-004a: regenerate keeps the approved answer and inserts a draft revision.

Bulk generation still skips an approved row. Explicit regenerate does not update
that row. Export and the questionnaire read keep the approved text until the
draft is approved, which supersedes the previous text.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import secrets
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.api.routes.answers import router as answers_router
from app.api.routes.questionnaires import router as questionnaires_router
from app.core.database import get_db
from app.core.session import sign_session
from app.models import (
    Answer,
    CustomRole,
    Question,
    Questionnaire,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
)

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "tc12004a_answer_revisions"
PARENT = "tc05001c_mfa_satisfied"
APPROVED_TEXT = "Human approved text"
APPROVED_CITATIONS = '[{"chunk_id": 1, "snippet": "approved snippet"}]'
FIRST_DRAFT = "Fresh draft from regenerate."
SECOND_DRAFT = "Second draft from regenerate."
FIRST_CITATIONS = [{"chunk_id": 41, "snippet": "synthetic evidence"}]


def _produced(text_value: str, fingerprint: str) -> dict:
    return {
        "text": text_value,
        "citations": FIRST_CITATIONS,
        "confidence": 88,
        "outcome_code": "grounded",
        "insufficient_reason": None,
        "gating_reason": None,
        "primary_categories_json": None,
        "evidence_fingerprint": fingerprint,
    }


def _raw_answer(db: Session, answer_id: int) -> dict:
    db.expire_all()
    row = (
        db.execute(text("SELECT * FROM answers WHERE id = :id"), {"id": answer_id}).mappings().one()
    )
    return dict(row)


def _revisions() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for path in (API_ROOT / "alembic" / "versions").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        revision = down = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "revision" in names and isinstance(node.value, ast.Constant):
                revision = node.value.value
            if "down_revision" in names and isinstance(node.value, ast.Constant):
                down = node.value.value
        if isinstance(revision, str):
            found[revision] = down if isinstance(down, str) else None
    return found


@pytest.mark.unit
def test_answer_revision_migration_stays_on_the_single_head():
    """Parent link stays put. A later revision may be the single head."""
    revisions = _revisions()
    assert revisions[REVISION] == PARENT
    assert len(REVISION) <= 32
    heads = [item for item in revisions if item not in set(revisions.values())]
    assert len(heads) == 1
    current: str | None = heads[0]
    seen: set[str] = set()
    while current and current not in seen:
        if current == REVISION:
            return
        seen.add(current)
        current = revisions.get(current)
    raise AssertionError(f"{REVISION} is not on the single head chain")


@pytest.fixture
def migration_db():
    path = API_ROOT / "alembic/versions/tc12004a_answer_revisions.py"
    spec = importlib.util.spec_from_file_location("tc12004a_migration_under_test", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def explicit_transactions(connection, _record):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE questions (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text(
                """
                CREATE TABLE answers (
                    id INTEGER PRIMARY KEY,
                    question_id INTEGER,
                    text TEXT,
                    status VARCHAR(32),
                    citations TEXT,
                    confidence INTEGER,
                    insufficient_reason VARCHAR(64),
                    gating_reason VARCHAR(64),
                    primary_categories_json TEXT,
                    evidence_fingerprint VARCHAR(64),
                    outcome_code VARCHAR(64),
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        connection.execute(text("INSERT INTO questions (id) VALUES (1)"))
        connection.execute(
            text(
                """
                INSERT INTO answers (
                    id, question_id, text, status, citations, confidence, outcome_code
                ) VALUES (7, 1, 'Human approved text', 'approved', '[]', 70, 'grounded')
                """
            )
        )

    def migrate(direction):
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                getattr(migration, direction)()

    def answer_row():
        with engine.connect() as connection:
            return dict(
                connection.execute(text("SELECT * FROM answers WHERE id = 7")).mappings().one()
            )

    try:
        yield engine, migrate, answer_row
    finally:
        engine.dispose()


@pytest.mark.unit
def test_upgrade_downgrade_upgrade_restores_revisions_and_leaves_the_answer(migration_db):
    engine, migrate, answer_row = migration_db
    before = answer_row()
    answer_columns = set(before)
    migrate("upgrade")
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "answer_revisions" in tables
        assert "tc12004a_revision_archive" not in tables
        answer_names = {column["name"] for column in inspect(connection).get_columns("answers")}
        assert answer_names == answer_columns
        connection.execute(
            text(
                """
                INSERT INTO answer_revisions (
                    answer_id, question_id, revision_number, text, citations, status
                ) VALUES (7, 1, 1, 'Fresh draft', '[{"chunk_id": 4}]', 'draft')
                """
            )
        )
    assert answer_row() == before
    migrate("downgrade")
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "answer_revisions" not in tables
        archived = connection.execute(
            text("SELECT text, status FROM tc12004a_revision_archive WHERE answer_id = 7")
        ).one()
        assert tuple(archived) == ("Fresh draft", "draft")
    assert answer_row() == before
    migrate("upgrade")
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "tc12004a_revision_archive" not in tables
        restored = connection.execute(
            text("SELECT text, status, revision_number FROM answer_revisions WHERE answer_id = 7")
        ).one()
        assert tuple(restored) == ("Fresh draft", "draft", 1)
    assert answer_row() == before


@pytest.fixture
def review_api(migrated_db):
    from app.core.database import SessionLocal

    db = SessionLocal()
    owned: dict[type, list[int]] = {
        Answer: [],
        Question: [],
        Questionnaire: [],
        CustomRole: [],
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
    workspace = add(Workspace, id=first, name="Revision A", slug=f"rev-a-{suffix}")
    other = add(Workspace, id=first + 1, name="Revision B", slug=f"rev-b-{suffix}")
    user = add(
        User,
        email=f"rev-{suffix}@example.com",
        password_hash="synthetic-unused",
        email_verified=True,
    )
    member = add(WorkspaceMember, workspace_id=workspace.id, user_id=user.id, role="reviewer")
    add(
        CustomRole,
        workspace_id=workspace.id,
        name="no-review",
        can_edit=False,
        can_review=False,
        can_export=False,
        can_admin=False,
    )
    sid = secrets.token_hex(16)
    add(UserSession, user_id=user.id, session_id=sid)
    questionnaire = add(
        Questionnaire,
        workspace_id=workspace.id,
        filename="synthetic.xlsx",
        status="parsed",
    )
    question = add(Question, questionnaire_id=questionnaire.id, text="Synthetic question?")
    approved = add(
        Answer,
        question_id=question.id,
        text=APPROVED_TEXT,
        status="approved",
        citations=APPROVED_CITATIONS,
        confidence=70,
        primary_categories_json='{"subjects":["synthetic"]}',
        evidence_fingerprint="approved-fp",
        outcome_code="grounded",
    )
    draft_answer = add(
        Answer,
        question_id=add(
            Question, questionnaire_id=questionnaire.id, text="Unapproved question?"
        ).id,
        text="Still a draft",
        status="draft",
    )
    foreign_question = add(
        Question,
        questionnaire_id=add(
            Questionnaire,
            workspace_id=other.id,
            filename="other.xlsx",
            status="parsed",
        ).id,
        text="Foreign question?",
    )
    foreign = add(
        Answer,
        question_id=foreign_question.id,
        text="Foreign approved",
        status="approved",
    )
    db.commit()

    app = FastAPI()
    app.include_router(answers_router, prefix="/api")
    app.include_router(questionnaires_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db

    @contextmanager
    def client(role="reviewer"):
        member.role = role
        db.commit()
        with TestClient(app) as http:
            http.cookies.set(
                "tc_session",
                sign_session(
                    user.id,
                    user.email,
                    workspace_id=workspace.id,
                    role=role,
                    session_id=sid,
                    max_age_seconds=3600,
                ),
            )
            yield http

    produced = _produced(FIRST_DRAFT, "draft-fp")

    def generator(_db, _question, _workspace_id, _questionnaire):
        return dict(produced)

    try:
        with patch(
            "app.api.routes.answers.generate_explicit_draft",
            side_effect=generator,
            create=True,
        ):
            yield {
                "db": db,
                "client": client,
                "workspace_id": workspace.id,
                "questionnaire_id": questionnaire.id,
                "question": question,
                "approved_id": approved.id,
                "draft_answer_id": draft_answer.id,
                "foreign_id": foreign.id,
                "produced": produced,
            }
    finally:
        db.rollback()
        for model in (
            Answer,
            Question,
            Questionnaire,
            CustomRole,
            UserSession,
            WorkspaceMember,
            User,
            Workspace,
        ):
            if owned[model]:
                db.query(model).filter(model.id.in_(owned[model])).delete(synchronize_session=False)
        db.commit()
        db.close()


def _drafts(db: Session, answer_id: int):
    from app.models.answer_revision import AnswerRevision

    db.expire_all()
    return (
        db.query(AnswerRevision)
        .filter(AnswerRevision.answer_id == answer_id)
        .order_by(AnswerRevision.revision_number)
        .all()
    )


def test_regenerate_leaves_the_approved_row_byte_identical_and_inserts_a_draft(review_api):
    env = review_api
    db = env["db"]
    before = _raw_answer(db, env["approved_id"])
    with env["client"]() as http:
        response = http.post(f"/api/answers/{env['approved_id']}/regenerate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == env["approved_id"]
    assert body["text"] == APPROVED_TEXT
    assert body["status"] == "approved"
    assert body["citations"] == APPROVED_CITATIONS
    draft = body["draft_revision"]
    assert draft["status"] == "draft"
    assert draft["revision_number"] == 1
    assert draft["text"] == FIRST_DRAFT
    assert json.loads(draft["citations"]) == FIRST_CITATIONS
    assert _raw_answer(db, env["approved_id"]) == before
    stored = _drafts(db, env["approved_id"])
    assert len(stored) == 1
    assert stored[0].text == FIRST_DRAFT
    assert stored[0].status == "draft"


def test_a_second_regenerate_keeps_the_approved_row_and_opens_a_new_draft(review_api):
    env = review_api
    db = env["db"]
    before = _raw_answer(db, env["approved_id"])
    with env["client"]() as http:
        first = http.post(f"/api/answers/{env['approved_id']}/regenerate")
        assert first.status_code == 200, first.text
        env["produced"]["text"] = SECOND_DRAFT
        env["produced"]["evidence_fingerprint"] = "draft-fp-2"
        second = http.post(f"/api/answers/{env['approved_id']}/regenerate")
    assert second.status_code == 200, second.text
    assert second.json()["text"] == APPROVED_TEXT
    assert second.json()["status"] == "approved"
    assert second.json()["draft_revision"]["text"] == SECOND_DRAFT
    assert second.json()["draft_revision"]["revision_number"] == 2
    assert _raw_answer(db, env["approved_id"]) == before
    stored = _drafts(db, env["approved_id"])
    assert [row.status for row in stored] == ["superseded", "draft"]
    assert stored[0].text == FIRST_DRAFT
    assert stored[1].text == SECOND_DRAFT


def test_read_and_export_keep_the_approved_revision_until_the_draft_is_approved(review_api):
    env = review_api
    db = env["db"]
    with env["client"]() as http:
        created = http.post(f"/api/answers/{env['approved_id']}/regenerate")
        assert created.status_code == 200, created.text
        read = http.get(
            f"/api/questionnaires/{env['questionnaire_id']}?workspace_id={env['workspace_id']}"
        )
    assert read.status_code == 200, read.text
    rows = {item["id"]: item for item in read.json()["questions"]}
    answer = rows[env["question"].id]["answer"]
    assert answer["text"] == APPROVED_TEXT
    assert answer["status"] == "approved"
    assert answer["citations"] == APPROVED_CITATIONS
    assert answer["draft_revision"]["text"] == FIRST_DRAFT
    assert answer["draft_revision"]["status"] == "draft"
    from app.services.answer_revisions import answers_for_export

    db.expire_all()
    saved = db.query(Answer).filter(Answer.id == env["approved_id"]).one()
    exported = answers_for_export([env["question"]], {env["question"].id: saved})
    assert APPROVED_TEXT in exported[env["question"].id]
    assert FIRST_DRAFT not in exported[env["question"].id]


def test_approving_the_draft_supersedes_the_previous_approved_text(review_api):
    env = review_api
    db = env["db"]
    with env["client"]() as http:
        created = http.post(f"/api/answers/{env['approved_id']}/regenerate")
        assert created.status_code == 200, created.text
        revision_id = created.json()["draft_revision"]["id"]
        approved = http.post(f"/api/answers/{env['approved_id']}/revisions/{revision_id}/approve")
        assert approved.status_code == 200, approved.text
        read = http.get(
            f"/api/questionnaires/{env['questionnaire_id']}?workspace_id={env['workspace_id']}"
        )
    body = approved.json()
    assert body["id"] == env["approved_id"]
    assert body["text"] == FIRST_DRAFT
    assert body["status"] == "approved"
    assert json.loads(body["citations"]) == FIRST_CITATIONS
    assert body["draft_revision"] is None
    stored = _drafts(db, env["approved_id"])
    by_status = {row.status: row for row in stored}
    assert by_status["superseded"].text == APPROVED_TEXT
    assert by_status["superseded"].citations == APPROVED_CITATIONS
    assert by_status["applied"].text == FIRST_DRAFT
    assert "draft" not in by_status
    answer = next(
        item["answer"] for item in read.json()["questions"] if item["id"] == env["question"].id
    )
    assert answer["text"] == FIRST_DRAFT
    assert answer["status"] == "approved"
    assert answer["draft_revision"] is None
    from app.services.answer_revisions import answers_for_export

    db.expire_all()
    saved = db.query(Answer).filter(Answer.id == env["approved_id"]).one()
    assert saved.id == env["approved_id"]
    exported = answers_for_export([env["question"]], {env["question"].id: saved})
    assert FIRST_DRAFT in exported[env["question"].id]
    assert APPROVED_TEXT not in exported[env["question"].id]


@pytest.mark.parametrize(
    ("case", "status"),
    (
        ("permission", 403),
        ("foreign", 403),
        ("unapproved", 409),
    ),
)
def test_a_rejected_regenerate_does_not_change_the_answer_row(review_api, case, status):
    env = review_api
    db = env["db"]
    if case == "permission":
        answer_id = env["approved_id"]
        role = "no-review"
    elif case == "foreign":
        answer_id = env["foreign_id"]
        role = "reviewer"
    else:
        answer_id = env["draft_answer_id"]
        role = "reviewer"
    before = _raw_answer(db, answer_id)
    with env["client"](role) as http:
        response = http.post(f"/api/answers/{answer_id}/regenerate")
    assert response.status_code == status, response.text
    assert _raw_answer(db, answer_id) == before
    assert _drafts(db, answer_id) == []
