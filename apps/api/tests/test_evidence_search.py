"""Tests for evidence search and retrieval APIs (P1-52)."""

import pytest
from app.models.evidence_item import EvidenceItem
from app.models.workspace import Workspace
from app.services import evidence_search_service as svc


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestEvidenceSearchService:
    def _seed(self, db_session):
        ws = db_session.query(Workspace).first()
        for i, st in enumerate(["manual", "integration", "ai"]):
            ev = EvidenceItem(workspace_id=ws.id, title=f"Search Test {st}", source_type=st)
            db_session.add(ev)
        db_session.flush()
        db_session.commit()
        return ws

    def test_search_all(self, db_session):
        ws = self._seed(db_session)
        result = svc.search(db_session, ws.id)
        assert result["total"] >= 3
        assert len(result["items"]) >= 3

    def test_search_by_source_type(self, db_session):
        ws = self._seed(db_session)
        result = svc.search(db_session, ws.id, source_type="integration")
        assert all(i["source_type"] == "integration" for i in result["items"])

    def test_search_by_title(self, db_session):
        ws = self._seed(db_session)
        result = svc.search(db_session, ws.id, title_query="Search Test")
        assert result["total"] >= 3

    def test_get_stats(self, db_session):
        ws = self._seed(db_session)
        stats = svc.get_stats(db_session, ws.id)
        assert stats["total"] >= 3
        assert "by_source_type" in stats

    def test_pagination(self, db_session):
        ws = self._seed(db_session)
        result = svc.search(db_session, ws.id, limit=2, offset=0)
        assert len(result["items"]) <= 2


class TestEvidenceSearchAPI:
    def test_search(self, admin_client):
        r = admin_client.get("/api/evidence-search")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_search_with_filters(self, admin_client):
        r = admin_client.get("/api/evidence-search?source_type=manual&limit=10")
        assert r.status_code == 200

    def test_stats(self, admin_client):
        r = admin_client.get("/api/evidence-search/stats")
        assert r.status_code == 200
        assert "total" in r.json()
