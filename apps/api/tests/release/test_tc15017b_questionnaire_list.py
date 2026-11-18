"""TC-15-017b: questionnaire list paging, row metadata, and mapping confirmation.

The list keeps the unpaged JSON array when page, page_size, sort, and order are
all absent. Sending any of those parameters returns one page. Each row reports
question and review counts, the newest parse job, job progress, needs_review,
and whether a suggested mapping still needs confirmation. Confirmation is a
workspace-scoped editor action. Reviewers can read it and cannot apply it.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

TABLES = (
    "question_mapping_preferences",
    "answers",
    "questions",
    "jobs",
    "questionnaires",
    "user_sessions",
    "workspace_members",
    "users",
    "workspaces",
)

_ROW_KEYS = {
    "question_count",
    "review_reviewed",
    "review_total",
    "job_id",
    "job_status",
    "job_progress",
    "mapping_ambiguous",
    "mapping_confirmation_url",
    "needs_review",
}


def _snapshot():
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        return {
            name: [tuple(row) for row in db.execute(text(f"SELECT * FROM {name} ORDER BY id"))]
            for name in TABLES
        }


def _delete_created(before, current) -> None:
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        for name in TABLES:
            old_ids = {row[0] for row in before[name]}
            created = [row[0] for row in current[name] if row[0] not in old_ids]
            if created:
                statement = text(f"DELETE FROM {name} WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                )
                db.execute(statement, {"ids": created})
        db.commit()


@pytest.fixture
def library(_ensure_test_data):
    """Two workspaces. The caller's library has counts, jobs, and mappings."""
    from app.core.database import SessionLocal
    from app.models import (
        Answer,
        Job,
        Question,
        Questionnaire,
        User,
        UserSession,
        Workspace,
        WorkspaceMember,
    )
    from app.models.ai_mapping import QuestionMappingPreference

    if not _ensure_test_data:
        pytest.fail("PostgreSQL is required for the questionnaire list contract")
    before = _snapshot()
    token = uuid.uuid4().hex
    try:
        with SessionLocal() as db:
            first = db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM workspaces")).scalar_one()
            own = Workspace(id=first, name="List own", slug=f"qnr-list-{token}")
            other = Workspace(id=first + 1, name="List other", slug=f"qnr-list-other-{token}")
            db.add_all([own, other])
            db.flush()
            actors = {}
            for role in ("editor", "reviewer"):
                user = User(
                    email=f"{role}-{token}@test.local",
                    password_hash="unused-signed-session",
                    display_name=role,
                    email_verified=True,
                )
                db.add(user)
                db.flush()
                db.add(WorkspaceMember(workspace_id=own.id, user_id=user.id, role=role))
                session_id = uuid.uuid4().hex
                db.add(UserSession(user_id=user.id, session_id=session_id))
                actors[role] = {
                    "user_id": user.id,
                    "email": user.email,
                    "role": role,
                    "session_id": session_id,
                    "workspace_id": own.id,
                }
            alpha = Questionnaire(
                workspace_id=own.id,
                filename="Alpha.xlsx",
                status="parsed",
                created_at=datetime(2026, 11, 2, 12, 0, 0),
            )
            zeta = Questionnaire(
                workspace_id=own.id,
                filename="Zeta.xlsx",
                status="parsed",
                created_at=datetime(2026, 11, 1, 12, 0, 0),
            )
            empty = Questionnaire(
                workspace_id=own.id,
                filename="Empty.xlsx",
                status="needs_review",
                parse_metadata=json.dumps(
                    {
                        "count": 0,
                        "questions": [],
                        "review": "No questions were detected in this workbook.",
                    }
                ),
                created_at=datetime(2026, 11, 3, 12, 0, 0),
            )
            archived = Questionnaire(
                workspace_id=own.id,
                filename="Archived.xlsx",
                status="parsed",
                deleted_at=datetime(2026, 11, 4, 12, 0, 0),
                created_at=datetime(2026, 11, 4, 8, 0, 0),
            )
            foreign = Questionnaire(
                workspace_id=other.id,
                filename="Foreign.xlsx",
                status="parsed",
                created_at=datetime(2026, 11, 5, 12, 0, 0),
            )
            db.add_all([alpha, zeta, empty, archived, foreign])
            db.flush()
            first_question = Question(
                questionnaire_id=alpha.id,
                text="Does the company encrypt data at rest?",
                mapping_version=1,
                answer_cell="D2",
            )
            second_question = Question(
                questionnaire_id=alpha.id,
                text="Is access reviewed at least quarterly?",
                mapping_version=1,
                answer_cell="D3",
            )
            db.add_all([first_question, second_question])
            db.flush()
            db.add(
                Answer(
                    question_id=first_question.id,
                    text="Yes.",
                    status="approved",
                )
            )
            db.add(
                Answer(
                    question_id=second_question.id,
                    text="Draft only.",
                    status="draft",
                )
            )
            suggested = QuestionMappingPreference(
                workspace_id=own.id,
                questionnaire_id=alpha.id,
                question_id=second_question.id,
                normalized_question_text=second_question.text,
                status="suggested",
                source="ai",
                approved=False,
            )
            approved = QuestionMappingPreference(
                workspace_id=own.id,
                questionnaire_id=zeta.id,
                normalized_question_text="Already confirmed",
                status="approved",
                source="manual",
                approved=True,
            )
            leaked = QuestionMappingPreference(
                workspace_id=other.id,
                questionnaire_id=zeta.id,
                normalized_question_text="PRIVATE other workspace suggestion",
                status="suggested",
                source="ai",
                approved=False,
            )
            db.add_all([suggested, approved, leaked])
            parse_job = Job(
                workspace_id=own.id,
                kind="parse_questionnaire",
                status="failed",
                payload=json.dumps({"questionnaire_id": alpha.id, "storage_key": "PRIVATE key"}),
                result=json.dumps({"count": 2}),
            )
            answer_job = Job(
                workspace_id=own.id,
                kind="generate_answers",
                status="running",
                payload=json.dumps({"questionnaire_id": alpha.id}),
                result=json.dumps({"generated": 4, "total": 10, "body": "PRIVATE"}),
            )
            broken_job = Job(
                workspace_id=own.id,
                kind="parse_questionnaire",
                status="completed",
                payload="{broken",
                result="{broken",
            )
            foreign_job = Job(
                workspace_id=other.id,
                kind="parse_questionnaire",
                status="completed",
                payload=json.dumps({"questionnaire_id": alpha.id}),
                result=json.dumps({"generated": 9, "total": 9}),
            )
            db.add_all([parse_job, answer_job, broken_job, foreign_job])
            db.commit()
            for row in (alpha, zeta, empty, archived, foreign, suggested, parse_job, answer_job):
                db.refresh(row)
            state = {
                "workspace_id": own.id,
                "other_workspace_id": other.id,
                "actors": actors,
                "alpha_id": alpha.id,
                "zeta_id": zeta.id,
                "empty_id": empty.id,
                "suggested_id": suggested.id,
                "parse_job_id": parse_job.id,
                "answer_job_id": answer_job.id,
                "foreign_job_id": foreign_job.id,
            }
        yield state
    finally:
        _delete_created(before, _snapshot())


@contextmanager
def _client(actor):
    from app.core.session import sign_session
    from app.main import app
    from tests.conftest import TEST_HEADERS

    client = TestClient(app, headers=TEST_HEADERS)
    try:
        if actor is not None:
            client.cookies.set(
                "tc_session",
                sign_session(
                    actor["user_id"],
                    actor["email"],
                    workspace_id=actor["workspace_id"],
                    role=actor["role"],
                    session_id=actor["session_id"],
                    max_age_seconds=3600,
                ),
            )
        yield client
    finally:
        client.close()


def _rows(body):
    if isinstance(body, list):
        return body
    assert isinstance(body, dict)
    return body["items"]


def _by_name(body, filename):
    return next(row for row in _rows(body) if row["filename"] == filename)


@pytest.mark.integration
def test_unpaged_list_reports_counts_jobs_and_needs_review(library):
    with _client(library["actors"]["reviewer"]) as client:
        response = client.get(f"/api/questionnaires/?workspace_id={library['workspace_id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert [row["filename"] for row in body] == ["Empty.xlsx", "Alpha.xlsx", "Zeta.xlsx"]
    assert "Foreign.xlsx" not in response.text
    assert "PRIVATE" not in response.text
    assert "Archived.xlsx" not in response.text
    alpha = _by_name(body, "Alpha.xlsx")
    assert _ROW_KEYS <= alpha.keys()
    assert alpha["question_count"] == 2
    assert alpha["review_reviewed"] == 1
    assert alpha["review_total"] == 2
    assert alpha["needs_review"] is False
    assert alpha["mapping_ambiguous"] is True
    assert alpha["mapping_confirmation_url"] == (
        f"/dashboard/questionnaires/{library['alpha_id']}/confirm-mapping"
    )
    assert alpha["job_id"] == library["parse_job_id"]
    assert alpha["job_status"] == "failed"
    assert alpha["job_progress"] == {"generated": 4, "total": 10}
    assert alpha["job_id"] != library["foreign_job_id"]
    zeta = _by_name(body, "Zeta.xlsx")
    assert zeta["mapping_ambiguous"] is False
    assert zeta["mapping_confirmation_url"] is None
    assert zeta["job_id"] is None
    assert zeta["job_progress"] is None
    assert zeta["question_count"] == 0
    assert zeta["review_reviewed"] == 0
    assert zeta["review_total"] == 0
    empty = _by_name(body, "Empty.xlsx")
    assert empty["needs_review"] is True
    assert empty["question_count"] == 0
    assert empty["review_reviewed"] == 0
    assert empty["review_total"] == 0
    assert empty["mapping_ambiguous"] is False


@pytest.mark.integration
def test_page_and_sort_return_one_page(library):
    workspace = library["workspace_id"]
    with _client(library["actors"]["reviewer"]) as client:
        first = client.get(
            f"/api/questionnaires/?workspace_id={workspace}"
            "&page=1&page_size=1&sort=created_at&order=desc"
        )
        second = client.get(
            f"/api/questionnaires/?workspace_id={workspace}"
            "&page=2&page_size=1&sort=filename&order=asc"
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    page = first.json()
    assert page["page"] == 1
    assert page["page_size"] == 1
    assert page["total"] == 3
    assert page["sort"] == "created_at"
    assert page["order"] == "desc"
    assert [row["filename"] for row in page["items"]] == ["Empty.xlsx"]
    assert [row["filename"] for row in second.json()["items"]] == ["Empty.xlsx"]
    assert second.json()["sort"] == "filename"
    assert second.json()["order"] == "asc"
    assert second.json()["total"] == 3


@pytest.mark.integration
def test_invalid_paging_is_rejected(library):
    workspace = library["workspace_id"]
    with _client(library["actors"]["reviewer"]) as client:
        rejected = [
            client.get(f"/api/questionnaires/?workspace_id={workspace}&sort=secret"),
            client.get(f"/api/questionnaires/?workspace_id={workspace}&order=sideways"),
            client.get(f"/api/questionnaires/?workspace_id={workspace}&page=0"),
            client.get(f"/api/questionnaires/?workspace_id={workspace}&page_size=101"),
        ]
    for response in rejected:
        assert response.status_code == 400, response.text
    with _client(None) as client:
        denied = client.get(f"/api/questionnaires/?workspace_id={workspace}&page=1")
    assert denied.status_code == 401


@pytest.mark.integration
def test_other_workspace_cannot_read_the_list_or_confirmation(library):
    with _client(library["actors"]["reviewer"]) as client:
        denied = client.get(f"/api/questionnaires/?workspace_id={library['other_workspace_id']}")
        missing = client.get(
            f"/api/questionnaires/{library['alpha_id']}/mapping-confirmation"
            f"?workspace_id={library['other_workspace_id']}"
        )
        foreign_row = client.get(
            f"/api/questionnaires/{library['alpha_id']}/mapping-confirmation"
            f"?workspace_id={library['workspace_id']}"
        )
    assert denied.status_code == 403, denied.text
    assert missing.status_code == 403, missing.text
    assert foreign_row.status_code == 200, foreign_row.text
    assert "PRIVATE" not in foreign_row.text
    assert "Foreign.xlsx" not in foreign_row.text


@pytest.mark.integration
def test_mapping_confirmation_is_editor_only_and_confirms_suggested_rows(library):
    url = (
        f"/api/questionnaires/{library['alpha_id']}/mapping-confirmation"
        f"?workspace_id={library['workspace_id']}"
    )
    with _client(library["actors"]["reviewer"]) as client:
        reading = client.get(url)
        refused = client.post(url, json={"mapping_ids": [library["suggested_id"]]})
    assert reading.status_code == 200, reading.text
    body = reading.json()
    assert body["mapping_ambiguous"] is True
    assert body["needs_review"] is False
    assert body["questionnaire_id"] == library["alpha_id"]
    assert [item["id"] for item in body["items"]] == [library["suggested_id"]]
    assert body["items"][0]["status"] == "suggested"
    assert body["items"][0]["question_text"] == "Is access reviewed at least quarterly?"
    assert refused.status_code == 403, refused.text

    with _client(library["actors"]["editor"]) as client:
        mixed = client.post(
            url,
            json={"mapping_ids": [library["suggested_id"], 2147483647]},
        )
        assert mixed.status_code == 400, mixed.text
        still = client.get(url)
        assert still.json()["mapping_ambiguous"] is True
        confirmed = client.post(url, json={"mapping_ids": [library["suggested_id"]]})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["ok"] is True
        assert confirmed.json()["confirmed"] == 1
        assert confirmed.json()["mapping_ambiguous"] is False
        after = client.get(url)
        assert after.json()["items"] == []
        assert after.json()["mapping_ambiguous"] is False
        listed = client.get(f"/api/questionnaires/?workspace_id={library['workspace_id']}")
    alpha = _by_name(listed.json(), "Alpha.xlsx")
    assert alpha["mapping_ambiguous"] is False
    assert alpha["mapping_confirmation_url"] is None
