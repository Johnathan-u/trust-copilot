"""Tests for customer-specific knowledge packs (P1-59)."""

import pytest
from app.models.workspace import Workspace
from app.services import knowledge_pack_service as kp


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestKnowledgePackService:
    def test_pack_structure(self, db_session):
        ws = db_session.query(Workspace).first()
        pack = kp.generate_knowledge_pack(db_session, ws.id)
        assert "categories" in pack
        assert "total_answers" in pack
        assert "total_categories" in pack
        assert "supporting_documents" in pack
        assert "generated_at" in pack

    def test_categorization(self):
        assert kp._categorize_question("How do you handle access control?") == "Access Control"
        assert kp._categorize_question("What encryption do you use?") == "Data Protection"
        assert kp._categorize_question("Describe your incident response") == "Incident Response"
        assert kp._categorize_question("random question") == "General"


class TestKnowledgePackAPI:
    def test_get_pack(self, admin_client):
        r = admin_client.get("/api/knowledge-packs")
        assert r.status_code == 200
        assert "categories" in r.json()
