"""Tests for case study template (P0-83)."""

import pytest
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services import case_study_service as cs


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


class TestCaseStudyService:
    def _get_workspace(self, db):
        ws = db.query(Workspace).first()
        assert ws
        return ws

    def test_get_template(self):
        template = cs.get_template()
        assert "sections" in template
        assert "suggested_metrics" in template
        assert len(template["sections"]) >= 5

    def test_create(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            result = cs.create(db, ws.id, "Acme Corp Case Study",
                               company_name="Acme Corp",
                               industry="FinTech",
                               challenge="Too many questionnaires")
            db.commit()
            assert result["title"] == "Acme Corp Case Study"
            assert result["company_name"] == "Acme Corp"
            assert result["status"] == "draft"
        finally:
            db.close()

    def test_list(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            cs.create(db, ws.id, "Test List Case Study")
            db.commit()
            cases = cs.list_all(db, ws.id)
            assert len(cases) >= 1
        finally:
            db.close()

    def test_update(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            created = cs.create(db, ws.id, "Update Test")
            db.commit()
            updated = cs.update(db, created["id"], challenge="Updated challenge", status="published")
            db.commit()
            assert updated["challenge"] == "Updated challenge"
            assert updated["status"] == "published"
            assert updated["published_at"] is not None
        finally:
            db.close()

    def test_delete(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            created = cs.create(db, ws.id, "Delete Test")
            db.commit()
            assert cs.delete(db, created["id"]) is True
            db.commit()
            assert cs.get(db, created["id"]) is None
        finally:
            db.close()

    def test_metrics_json(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            metrics = {"hours_saved": 240, "accuracy_rate_pct": 95}
            result = cs.create(db, ws.id, "Metrics Test", metrics=metrics)
            db.commit()
            assert result["metrics"]["hours_saved"] == 240
        finally:
            db.close()


class TestCaseStudyAPI:
    def test_get_template(self, admin_client):
        r = admin_client.get("/api/case-studies/template")
        assert r.status_code == 200
        assert "sections" in r.json()

    def test_create_case_study(self, admin_client):
        r = admin_client.post("/api/case-studies", json={
            "title": "API Test Case Study",
            "company_name": "TestCo",
        })
        assert r.status_code == 200
        assert r.json()["title"] == "API Test Case Study"

    def test_list_case_studies(self, admin_client):
        r = admin_client.get("/api/case-studies")
        assert r.status_code == 200
        assert "case_studies" in r.json()

    def test_update_case_study(self, admin_client):
        r = admin_client.post("/api/case-studies", json={"title": "Patch Test"})
        case_id = r.json()["id"]
        r = admin_client.patch(f"/api/case-studies/{case_id}", json={"challenge": "Updated"})
        assert r.status_code == 200
        assert r.json()["challenge"] == "Updated"

    def test_delete_case_study(self, admin_client):
        r = admin_client.post("/api/case-studies", json={"title": "Delete API Test"})
        case_id = r.json()["id"]
        r = admin_client.delete(f"/api/case-studies/{case_id}")
        assert r.status_code == 200

    def test_editor_can_read(self, editor_client, admin_client):
        admin_client.post("/api/case-studies", json={"title": "Editor Read Test"})
        r = editor_client.get("/api/case-studies")
        assert r.status_code == 200

    def test_editor_cannot_create(self, editor_client):
        r = editor_client.post("/api/case-studies", json={"title": "Nope"})
        assert r.status_code == 403
