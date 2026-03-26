"""Tests for ingestion pipeline (P1-16)."""

import pytest
from app.models.workspace import Workspace
from app.services import ingestion_pipeline_service as ips


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestIngestionService:
    def test_ingest_evidence(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ips.ingest_evidence(db_session, ws.id, "manual", "Test Evidence")
        db_session.commit()
        assert result["source_type"] == "manual"
        assert result["id"] is not None

    def test_ingest_batch(self, db_session):
        ws = db_session.query(Workspace).first()
        items = [
            {"title": "Batch 1"},
            {"title": "Batch 2"},
            {"title": "Batch 3"},
        ]
        result = ips.ingest_batch(db_session, ws.id, "aws", items)
        db_session.commit()
        assert result["ingested"] == 3

    def test_stats(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ips.get_ingestion_stats(db_session, ws.id)
        assert "by_source" in result
        assert "total" in result


class TestIngestionAPI:
    def test_ingest(self, admin_client):
        r = admin_client.post("/api/ingestion", json={
            "source_type": "manual",
            "title": "API Test Evidence",
        })
        assert r.status_code == 200
        assert r.json()["source_type"] == "manual"

    def test_batch(self, admin_client):
        r = admin_client.post("/api/ingestion/batch", json={
            "source_type": "github",
            "items": [{"title": "GH-1"}, {"title": "GH-2"}],
        })
        assert r.status_code == 200
        assert r.json()["ingested"] == 2

    def test_stats(self, admin_client):
        r = admin_client.get("/api/ingestion/stats")
        assert r.status_code == 200
        assert "total" in r.json()
