"""generate_answers_for_questionnaire must fail clearly when OpenAI is not configured."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Question, Questionnaire
from app.services.answer_generation import generate_answers_for_questionnaire


def test_raises_when_no_api_key_and_questions_exist():
    db, _ = _mock_db_with_questions(2)
    with patch("app.core.config.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = ""
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            generate_answers_for_questionnaire(db, 1, 1)


def test_returns_zero_when_no_key_and_no_questions():
    db, _ = _mock_db_with_questions(0)
    with patch("app.core.config.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = None
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        assert generate_answers_for_questionnaire(db, 1, 1) == 0


def test_api_post_generate_returns_503_without_openai_key(client: TestClient, db_session: Session) -> None:
    """POST /exports/generate must not enqueue a job when OPENAI is unset and questions exist."""
    qnr = db_session.query(Questionnaire).filter(Questionnaire.workspace_id == 1).first()
    if not qnr:
        qnr = Questionnaire(
            workspace_id=1,
            filename="api_openai_test.xlsx",
            status="parsed",
            storage_key="test-key-openai",
        )
        db_session.add(qnr)
        db_session.commit()
        db_session.refresh(qnr)
    if not db_session.query(Question).filter(Question.questionnaire_id == qnr.id).first():
        db_session.add(Question(questionnaire_id=qnr.id, text="API test question?"))
        db_session.commit()

    with patch("app.api.routes.exports.get_settings") as mock_gs:
        cfg = MagicMock()
        cfg.openai_api_key = ""
        cfg.completion_model = "gpt-4o-mini"
        mock_gs.return_value = cfg
        r_login = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
        assert r_login.status_code == 200
        r = client.post(f"/api/exports/generate/{qnr.id}?workspace_id=1", json={})
        assert r.status_code == 503
        detail = (r.json() or {}).get("detail", "")
        assert "openai" in str(detail).lower() or "OPENAI" in str(detail)


def _mock_db_with_questions(n: int):
    questionnaire = MagicMock(id=1, workspace_id=1)
    questions = [MagicMock(id=i + 1, text=f"Q{i}?") for i in range(n)]
    query_qnr = MagicMock()
    query_qnr.filter.return_value.first.return_value = questionnaire
    query_questions = MagicMock()
    query_questions.filter.return_value.all.return_value = questions
    db = MagicMock()
    db.query.side_effect = [query_qnr, query_questions]
    db.commit = MagicMock()
    return db, questions
