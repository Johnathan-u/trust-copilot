"""Tests for signal mapping (P1-32)."""

import pytest
from app.models.workspace import Workspace
from app.services import signal_mapping_service as sm


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


class TestSignalMappingService:
    def test_get_signal_map(self):
        m = sm.get_signal_map()
        assert len(m) >= 20
        assert "aws.iam.mfa_enabled" in m

    def test_controls_for_signal(self):
        ctrls = sm.get_controls_for_signal("aws.iam.mfa_enabled")
        assert "AC-2" in ctrls
        assert "IA-2" in ctrls

    def test_signals_for_control(self):
        signals = sm.get_signals_for_control("AC-2")
        assert len(signals) >= 3

    def test_evaluate_signal(self, db_session):
        ws = db_session.query(Workspace).first()
        result = sm.evaluate_signal(db_session, ws.id, "aws.iam.mfa_enabled", True)
        assert result["signal"] == "aws.iam.mfa_enabled"
        assert result["mapped_controls"] >= 1
        assert "affected_controls" in result

    def test_coverage_matrix(self, db_session):
        ws = db_session.query(Workspace).first()
        matrix = sm.get_coverage_matrix(db_session, ws.id)
        assert "total_controls" in matrix
        assert "covered" in matrix
        assert "uncovered" in matrix


class TestSignalMappingAPI:
    def test_get_map(self, admin_client):
        r = admin_client.get("/api/signal-mappings")
        assert r.status_code == 200
        assert "mappings" in r.json()

    def test_coverage(self, admin_client):
        r = admin_client.get("/api/signal-mappings/coverage")
        assert r.status_code == 200
        assert "total_controls" in r.json()

    def test_evaluate(self, admin_client):
        r = admin_client.post("/api/signal-mappings/evaluate", json={
            "signal": "aws.iam.mfa_enabled",
            "value": True,
        })
        assert r.status_code == 200

    def test_editor_can_read(self, editor_client):
        r = editor_client.get("/api/signal-mappings")
        assert r.status_code == 200

    def test_editor_cannot_evaluate(self, editor_client):
        r = editor_client.post("/api/signal-mappings/evaluate", json={
            "signal": "aws.iam.mfa_enabled",
            "value": True,
        })
        assert r.status_code == 403
