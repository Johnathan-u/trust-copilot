"""Tests for benchmark dashboard (P0-84)."""

import pytest
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services import benchmark_service as bs


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return client


@pytest.fixture
def editor_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert r.status_code == 200, f"Editor login failed: {r.text}"
    return client


class TestBenchmarkService:
    def _get_workspace(self, db):
        ws = db.query(Workspace).first()
        assert ws
        return ws

    def test_benchmarks_structure(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            data = bs.get_benchmarks(db, ws.id)
            assert "questionnaire_metrics" in data
            assert "answer_metrics" in data
            assert "evidence_metrics" in data
            assert "ai_usage" in data
            assert "generated_at" in data
        finally:
            db.close()

    def test_questionnaire_metrics(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            data = bs.get_benchmarks(db, ws.id)
            qm = data["questionnaire_metrics"]
            assert "total_questionnaires" in qm
            assert "avg_job_turnaround_seconds" in qm
            assert isinstance(qm["total_questionnaires"], int)
        finally:
            db.close()

    def test_answer_metrics(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            data = bs.get_benchmarks(db, ws.id)
            am = data["answer_metrics"]
            assert "total_questions" in am
            assert "total_answers" in am
            assert "coverage_pct" in am
            assert "avg_confidence" in am
        finally:
            db.close()

    def test_evidence_metrics(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            data = bs.get_benchmarks(db, ws.id)
            em = data["evidence_metrics"]
            assert "total_documents" in em
            assert "evidence_gaps" in em
        finally:
            db.close()

    def test_ai_usage_periods(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            data = bs.get_benchmarks(db, ws.id)
            ai = data["ai_usage"]
            assert "periods" in ai
            assert isinstance(ai["periods"], list)
        finally:
            db.close()


class TestBenchmarkAPI:
    def test_get_benchmarks(self, admin_client):
        r = admin_client.get("/api/benchmarks")
        assert r.status_code == 200
        data = r.json()
        assert "questionnaire_metrics" in data

    def test_editor_can_access(self, editor_client):
        r = editor_client.get("/api/benchmarks")
        assert r.status_code == 200
