"""Tests for evidence diff viewer (P1-45)."""

import pytest
from app.models.workspace import Workspace
from app.services import evidence_diff_service as ed


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestEvidenceDiffService:
    def test_diff_snapshots_needs_two(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ed.diff_control_snapshots(db_session, ws.id, 999)
        assert result["diff"] is None

    def test_diff_evidence_items(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ed.diff_evidence_items(db_session, ws.id, 1)
        assert "total_evidence" in result
        assert "fresh" in result
        assert "stale" in result


class TestEvidenceDiffAPI:
    def test_snapshot_diff(self, admin_client):
        r = admin_client.get("/api/evidence-diff/snapshots/1")
        assert r.status_code == 200

    def test_evidence_diff(self, admin_client):
        r = admin_client.get("/api/evidence-diff/evidence/1")
        assert r.status_code == 200
        assert "total_evidence" in r.json()
