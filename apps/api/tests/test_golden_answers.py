"""Tests for golden answer library (P1-71, P1-73, P1-74, P1-75, P1-76)."""

import pytest
from app.models.workspace import Workspace
from app.services import golden_answer_service as ga


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


@pytest.fixture
def editor_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert r.status_code == 200
    return client


class TestGoldenAnswerService:
    def test_create(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ga.create_golden_answer(db_session, ws.id, "What is MFA?", "Multi-factor authentication...",
                                          category="Access Control")
        db_session.commit()
        assert result["question_text"] == "What is MFA?"
        assert result["status"] == "approved"
        assert result["expires_at"] is not None

    def test_list_and_filter(self, db_session):
        ws = db_session.query(Workspace).first()
        ga.create_golden_answer(db_session, ws.id, "Q1", "A1", category="Security")
        ga.create_golden_answer(db_session, ws.id, "Q2", "A2", category="Privacy")
        db_session.commit()
        all_answers = ga.list_golden_answers(db_session, ws.id)
        assert len(all_answers) >= 2
        sec = ga.list_golden_answers(db_session, ws.id, category="Security")
        assert all(a["category"] == "Security" for a in sec)

    def test_review_resets_expiry(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Review Q", "Review A")
        db_session.commit()
        reviewed = ga.review_golden_answer(db_session, created["id"])
        db_session.commit()
        assert reviewed["status"] == "approved"
        assert reviewed["last_reviewed_at"] is not None

    def test_customer_override(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ga.create_golden_answer(db_session, ws.id, "Override Q", "Custom A",
                                          customer_override_for="Acme Corp")
        db_session.commit()
        assert result["customer_override_for"] == "Acme Corp"
        overrides = ga.list_golden_answers(db_session, ws.id, customer="Acme Corp")
        assert len(overrides) >= 1

    def test_lineage(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Lineage Q", "Lineage A",
                                           control_ids=[1, 2], evidence_ids=[3])
        db_session.commit()
        lineage = ga.get_lineage(db_session, created["id"])
        assert lineage["control_ids"] == [1, 2]
        assert lineage["evidence_ids"] == [3]

    def test_reuse_counter(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Reuse Q", "Reuse A")
        db_session.commit()
        ga.record_reuse(db_session, created["id"])
        ga.record_reuse(db_session, created["id"])
        db_session.commit()
        result = ga.get_golden_answer(db_session, created["id"])
        assert result["reuse_count"] == 2

    def test_find_similar(self, db_session):
        ws = db_session.query(Workspace).first()
        ga.create_golden_answer(db_session, ws.id, "How do you handle encryption at rest?", "We use AES-256...")
        db_session.commit()
        similar = ga.find_similar(db_session, ws.id, "encryption at rest policy")
        assert len(similar) >= 1

    def test_expiring(self, db_session):
        ws = db_session.query(Workspace).first()
        ga.create_golden_answer(db_session, ws.id, "Expiring Q", "Expiring A", review_cycle_days=1)
        db_session.commit()
        expiring = ga.get_expiring(db_session, ws.id, within_days=365)
        assert len(expiring) >= 1


class TestGoldenAnswerAPI:
    def test_create(self, admin_client):
        r = admin_client.post("/api/golden-answers", json={
            "question_text": "API Q",
            "answer_text": "API A",
            "category": "General",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_list(self, admin_client):
        r = admin_client.get("/api/golden-answers")
        assert r.status_code == 200
        assert "answers" in r.json()

    def test_lineage(self, admin_client):
        r = admin_client.post("/api/golden-answers", json={
            "question_text": "Lineage API Q",
            "answer_text": "Lineage API A",
        })
        ga_id = r.json()["id"]
        r = admin_client.get(f"/api/golden-answers/{ga_id}/lineage")
        assert r.status_code == 200
        assert "control_ids" in r.json()

    def test_similar(self, admin_client):
        r = admin_client.post("/api/golden-answers/similar", json={
            "question_text": "encryption at rest",
        })
        assert r.status_code == 200
        assert "similar" in r.json()

    def test_expiring(self, admin_client):
        r = admin_client.get("/api/golden-answers/expiring?within_days=365")
        assert r.status_code == 200
        assert "expiring" in r.json()

    def test_editor_cannot_create(self, editor_client):
        r = editor_client.post("/api/golden-answers", json={
            "question_text": "X", "answer_text": "Y",
        })
        assert r.status_code == 403

    def test_editor_can_read(self, editor_client):
        r = editor_client.get("/api/golden-answers")
        assert r.status_code == 200
