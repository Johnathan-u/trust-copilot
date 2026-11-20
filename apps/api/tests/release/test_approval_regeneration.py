"""TC-12-004b: named release check for approved-answer regeneration.

Cached and uncached generation must leave an approved answer's text, citations,
and status in place. An explicit regenerate inserts a draft revision beside that
row. Read and export keep the approved text until the draft is approved.

The fixtures are synthetic. This file does not accept TC-12-004.
"""

from __future__ import annotations

import json
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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
    CustomRole,
    Job,
    JobStatus,
    Question,
    Questionnaire,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.models.answer_revision import AnswerRevision
from app.services.answer_cache import get as answer_cache_get
from app.services.answer_cache import set as answer_cache_set
from app.services.question_normalizer import (
    evidence_fingerprint_hash,
    normalize_question,
    question_cache_hash,
)

WS = 1
APPROVED_TEXT = "Human approved text"
APPROVED_CITATIONS = '[{"chunk_id": 7, "snippet": "approved human citation"}]'
CACHE_TEXT = "Cached draft that must not replace the approved answer."
CACHE_CITATIONS = [{"chunk_id": 9, "snippet": "cached citation that must not land"}]
DRAFT_TEXT = "Fresh draft from regenerate."
DRAFT_CITATIONS = [{"chunk_id": 41, "snippet": "synthetic evidence"}]
STYLE = "balanced"
EMPTY_FINGERPRINT = evidence_fingerprint_hash([])

_LEAK_TABLES = (
    "answer_revisions",
    "evidence_gaps",
    "question_mapping_signals",
    "question_mapping_preferences",
    "export_records",
    "answers",
    "questions",
    "chunks",
    "job_effects",
    "questionnaires",
    "documents",
    "jobs",
    "answer_cache",
    "workspace_usage",
    "idempotency_keys",
    "audit_events",
    "in_app_notifications",
)


def _watermarks(session: Session) -> dict[str, int]:
    marks: dict[str, int] = {}
    for table in _LEAK_TABLES:
        marks[table] = int(
            session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar() or 0
        )
    return marks


def _delete_after(session: Session, marks: dict[str, int]) -> None:
    session.rollback()
    session.execute(
        text("DELETE FROM answer_cache WHERE answer_text = :text"), {"text": CACHE_TEXT}
    )
    for table, mark in marks.items():
        session.execute(text(f"DELETE FROM {table} WHERE id > :mark"), {"mark": mark})
    session.commit()


def _raw_answer(db: Session, answer_id: int) -> dict:
    db.expire_all()
    row = (
        db.execute(text("SELECT * FROM answers WHERE id = :id"), {"id": answer_id}).mappings().one()
    )
    return dict(row)


def _question_hash(question_text: str) -> str:
    return question_cache_hash(normalize_question(question_text))


@pytest.fixture
def db(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    session = SessionLocal()
    marks = _watermarks(session)
    try:
        yield session
    finally:
        try:
            _delete_after(session, marks)
        finally:
            session.close()


def _approved_pair(db: Session, tag: str) -> tuple[Questionnaire, Question, Question, Answer]:
    questionnaire = Questionnaire(
        workspace_id=WS,
        storage_key=None,
        filename="synthetic.xlsx",
        status="parsed",
    )
    db.add(questionnaire)
    db.commit()
    approved_question = Question(
        questionnaire_id=questionnaire.id,
        text=f"Synthetic approved question {tag}?",
    )
    open_question = Question(
        questionnaire_id=questionnaire.id,
        text=f"Synthetic open question {tag}?",
    )
    db.add_all([approved_question, open_question])
    db.commit()
    approved = Answer(
        question_id=approved_question.id,
        text=APPROVED_TEXT,
        status="approved",
        citations=APPROVED_CITATIONS,
        confidence=70,
        outcome_code="grounded",
        evidence_fingerprint="approved-fp",
    )
    db.add(approved)
    db.commit()
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    db.execute(
        text("UPDATE answers SET created_at = :ts, updated_at = :ts WHERE id = :id"),
        {"ts": past, "id": approved.id},
    )
    db.commit()
    return questionnaire, approved_question, open_question, approved


def _run_generate(db: Session, questionnaire_id: int):
    from app import worker
    from app.core.config import get_settings

    job = Job(
        workspace_id=WS,
        kind="generate_answers",
        status=JobStatus.RUNNING.value,
        attempt=1,
        payload="{}",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
    )
    db.add(job)
    db.commit()
    payload = {
        "questionnaire_id": questionnaire_id,
        "workspace_id": WS,
        "response_style": STYLE,
    }
    job.payload = json.dumps(payload)
    db.commit()

    def no_llm(*_args, **_kwargs):
        raise AssertionError("the model must not be called for this run")

    get_settings.cache_clear()
    try:
        with (
            patch(
                "app.services.answer_generation.embed_texts",
                lambda texts, on_failure=None: [[0.001] * 8 for _ in texts],
            ),
            patch(
                "app.services.answer_generation.RetrievalService.batch_search",
                lambda self, ws, queries, **kwargs: [[] for _ in queries],
            ),
            patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
            patch("app.services.answer_generation._completion_create_with_retry", no_llm),
            patch(
                "app.services.answer_generation.generate_gaps_for_questionnaire",
                return_value={"generated": 0},
            ),
        ):
            worker.run_generate_answers(job, db, payload)
    finally:
        get_settings.cache_clear()
    db.expire_all()
    return job


def test_cached_regeneration_does_not_replace_approved_text_citations_or_status(db, monkeypatch):
    """A matching answer-cache row is not written onto an approved answer."""
    from app.core.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-synthetic-offline-key")
    get_settings.cache_clear()
    questionnaire, approved_question, open_question, approved = _approved_pair(db, "cache")
    answer_cache_set(
        db,
        WS,
        _question_hash(approved_question.text),
        STYLE,
        EMPTY_FINGERPRINT,
        CACHE_TEXT,
        CACHE_CITATIONS,
        91,
    )
    planted = answer_cache_get(
        db, WS, _question_hash(approved_question.text), STYLE, EMPTY_FINGERPRINT
    )
    assert planted is not None
    assert planted["text"] == CACHE_TEXT
    assert planted["citations"] == CACHE_CITATIONS
    before = _raw_answer(db, approved.id)

    job = _run_generate(db, questionnaire.id)

    assert _raw_answer(db, approved.id) == before
    saved = db.query(Answer).filter(Answer.id == approved.id).one()
    assert saved.text == APPROVED_TEXT
    assert saved.citations == APPROVED_CITATIONS
    assert saved.status == "approved"
    revisions = db.query(AnswerRevision).filter(AnswerRevision.answer_id == approved.id).all()
    assert revisions == []
    stats = json.loads(job.result)["stats"]
    assert stats["skipped_protected"] == 1
    open_answer = db.query(Answer).filter(Answer.question_id == open_question.id).one()
    assert open_answer.text != APPROVED_TEXT
    assert open_answer.status == "insufficient_evidence"
    still_cached = answer_cache_get(
        db, WS, _question_hash(approved_question.text), STYLE, EMPTY_FINGERPRINT
    )
    assert still_cached is not None
    assert still_cached["text"] == CACHE_TEXT
    assert still_cached["citations"] == CACHE_CITATIONS


def test_uncached_regeneration_does_not_replace_approved_text_citations_or_status(db, monkeypatch):
    """Generation with no cache row still leaves the approved text, citations, and status."""
    from app.core.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-synthetic-offline-key")
    get_settings.cache_clear()
    questionnaire, approved_question, open_question, approved = _approved_pair(db, "fresh")
    assert (
        answer_cache_get(db, WS, _question_hash(approved_question.text), STYLE, EMPTY_FINGERPRINT)
        is None
    )
    before = _raw_answer(db, approved.id)

    job = _run_generate(db, questionnaire.id)

    assert _raw_answer(db, approved.id) == before
    saved = db.query(Answer).filter(Answer.id == approved.id).one()
    assert saved.text == APPROVED_TEXT
    assert saved.citations == APPROVED_CITATIONS
    assert saved.status == "approved"
    assert db.query(AnswerRevision).filter(AnswerRevision.answer_id == approved.id).count() == 0
    assert json.loads(job.result)["stats"]["skipped_protected"] == 1
    open_answer = db.query(Answer).filter(Answer.question_id == open_question.id).one()
    assert open_answer.status == "insufficient_evidence"
    assert APPROVED_CITATIONS not in (open_answer.citations or "")


def _produced() -> dict:
    return {
        "text": DRAFT_TEXT,
        "citations": DRAFT_CITATIONS,
        "confidence": 88,
        "outcome_code": "grounded",
        "insufficient_reason": None,
        "gating_reason": None,
        "primary_categories_json": None,
        "evidence_fingerprint": "draft-fp",
    }


@pytest.fixture
def review_api(migrated_db):
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
    workspace = add(Workspace, id=first, name="Regen A", slug=f"regen-a-{suffix}")
    other = add(Workspace, id=first + 1, name="Regen B", slug=f"regen-b-{suffix}")
    user = add(
        User,
        email=f"regen-{suffix}@example.com",
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
    session_id = secrets.token_hex(16)
    add(UserSession, user_id=user.id, session_id=session_id)
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
        outcome_code="grounded",
        evidence_fingerprint="approved-fp",
    )
    draft_answer = add(
        Answer,
        question_id=add(
            Question, questionnaire_id=questionnaire.id, text="Unapproved question?"
        ).id,
        text="Still a draft",
        status="draft",
        citations="[]",
    )
    foreign = add(
        Answer,
        question_id=add(
            Question,
            questionnaire_id=add(
                Questionnaire,
                workspace_id=other.id,
                filename="other.xlsx",
                status="parsed",
            ).id,
            text="Foreign question?",
        ).id,
        text="Foreign approved",
        status="approved",
        citations="[]",
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
                    session_id=session_id,
                    max_age_seconds=3600,
                ),
            )
            yield http

    try:
        with patch(
            "app.api.routes.answers.generate_explicit_draft",
            return_value=_produced(),
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


def _drafts(db: Session, answer_id: int) -> list[AnswerRevision]:
    db.expire_all()
    return (
        db.query(AnswerRevision)
        .filter(AnswerRevision.answer_id == answer_id)
        .order_by(AnswerRevision.revision_number)
        .all()
    )


def test_explicit_regenerate_keeps_the_approved_row_until_reapproval(review_api):
    """The draft sits beside the approved row. Export uses the approved text until approval."""
    from app.services.answer_revisions import answers_for_export

    env = review_api
    db = env["db"]
    before = _raw_answer(db, env["approved_id"])
    with env["client"]() as http:
        created = http.post(f"/api/answers/{env['approved_id']}/regenerate")
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["text"] == APPROVED_TEXT
        assert body["status"] == "approved"
        assert body["citations"] == APPROVED_CITATIONS
        draft = body["draft_revision"]
        assert draft["status"] == "draft"
        assert draft["text"] == DRAFT_TEXT
        assert json.loads(draft["citations"]) == DRAFT_CITATIONS
        assert _raw_answer(db, env["approved_id"]) == before
        read = http.get(
            f"/api/questionnaires/{env['questionnaire_id']}?workspace_id={env['workspace_id']}"
        )
        assert read.status_code == 200, read.text
        rows = {item["id"]: item for item in read.json()["questions"]}
        answer = rows[env["question"].id]["answer"]
        assert answer["text"] == APPROVED_TEXT
        assert answer["status"] == "approved"
        assert answer["citations"] == APPROVED_CITATIONS
        assert answer["draft_revision"]["text"] == DRAFT_TEXT
        db.expire_all()
        saved = db.query(Answer).filter(Answer.id == env["approved_id"]).one()
        exported = answers_for_export([env["question"]], {env["question"].id: saved})
        assert APPROVED_TEXT in exported[env["question"].id]
        assert DRAFT_TEXT not in exported[env["question"].id]
        approved = http.post(f"/api/answers/{env['approved_id']}/revisions/{draft['id']}/approve")
        assert approved.status_code == 200, approved.text
    after = _raw_answer(db, env["approved_id"])
    assert after["text"] == DRAFT_TEXT
    assert after["status"] == "approved"
    assert json.loads(after["citations"]) == DRAFT_CITATIONS
    assert after["id"] == before["id"]
    stored = _drafts(db, env["approved_id"])
    by_status = {row.status: row for row in stored}
    assert by_status["superseded"].text == APPROVED_TEXT
    assert by_status["superseded"].citations == APPROVED_CITATIONS
    assert by_status["applied"].text == DRAFT_TEXT
    assert "draft" not in by_status
    db.expire_all()
    saved = db.query(Answer).filter(Answer.id == env["approved_id"]).one()
    exported = answers_for_export([env["question"]], {env["question"].id: saved})
    assert DRAFT_TEXT in exported[env["question"].id]
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
