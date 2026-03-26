"""Tests for feedback capture (P1-77)."""

import pytest
from app.models.workspace import Workspace
from app.models.questionnaire import Questionnaire
from app.services import feedback_capture_service as fc


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestFeedbackCaptureService:
    def test_capture_feedback(self, db_session):
        ws = db_session.query(Workspace).first()
        q = db_session.query(Questionnaire).filter(Questionnaire.workspace_id == ws.id).first()
        if not q:
            pytest.skip("No questionnaires")
        result = fc.capture_feedback(db_session, ws.id, q.id, "quality", feedback_text="Good answers")
        assert result["status"] == "captured"
        assert result["feedback_type"] == "quality"

    def test_invalid_type(self, db_session):
        ws = db_session.query(Workspace).first()
        result = fc.capture_feedback(db_session, ws.id, 1, "invalid_type")
        assert "error" in result

    def test_feedback_summary(self, db_session):
        ws = db_session.query(Workspace).first()
        result = fc.get_feedback_summary(db_session, ws.id)
        assert "total_questionnaires" in result
        assert "approval_rate" in result


class TestFeedbackCaptureAPI:
    def test_capture(self, admin_client, db_session):
        q = db_session.query(Questionnaire).first()
        if not q:
            pytest.skip("No questionnaires")
        r = admin_client.post("/api/feedback", json={
            "questionnaire_id": q.id,
            "feedback_type": "general",
            "feedback_text": "API test",
        })
        assert r.status_code in (200, 400)

    def test_summary(self, admin_client):
        r = admin_client.get("/api/feedback/summary")
        assert r.status_code == 200
        assert "total_questionnaires" in r.json()
