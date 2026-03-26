"""Tests for confidence-based routing (P1-57)."""

import pytest
from app.services import confidence_routing_service as svc


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


class TestConfidenceRoutingService:
    def test_route_nonexistent(self, db_session):
        result = svc.route_question(db_session, 99999)
        assert "error" in result

    def test_thresholds(self):
        result = svc.get_thresholds()
        assert "high_threshold" in result
        assert "low_threshold" in result

    def test_set_thresholds(self):
        svc.set_thresholds(80, 50)
        result = svc.get_thresholds()
        assert result["high_threshold"] == 80
        assert result["low_threshold"] == 50
        svc.set_thresholds(70, 40)

    def test_route_batch_empty(self, db_session):
        result = svc.route_batch(db_session, [])
        assert result["total"] == 0


class TestConfidenceRoutingAPI:
    def test_get_thresholds(self, admin_client):
        r = admin_client.get("/api/confidence-routing/thresholds")
        assert r.status_code == 200
        assert "high_threshold" in r.json()

    def test_set_thresholds(self, admin_client):
        r = admin_client.post("/api/confidence-routing/thresholds", json={"high": 80, "low": 50})
        assert r.status_code == 200
        admin_client.post("/api/confidence-routing/thresholds", json={"high": 70, "low": 40})

    def test_editor_cannot_set_thresholds(self, editor_client):
        r = editor_client.post("/api/confidence-routing/thresholds", json={"high": 80, "low": 50})
        assert r.status_code == 403

    def test_batch(self, admin_client):
        r = admin_client.post("/api/confidence-routing/batch", json={"question_ids": []})
        assert r.status_code == 200
        assert r.json()["total"] == 0
