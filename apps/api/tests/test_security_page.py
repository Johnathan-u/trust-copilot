"""Tests for public security page (P0-82)."""

import pytest
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services import security_page_service as sp
from app.services import security_faq_service as faq_svc


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


class TestSecurityPageService:
    def _get_workspace(self, db):
        ws = db.query(Workspace).first()
        assert ws
        return ws

    def test_page_structure(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            faq_svc.seed_defaults(db, ws.id)
            db.commit()
            page = sp.get_public_security_page(db, ws.id)
            assert page["title"] == "Security & Data Handling"
            assert "sections" in page
            assert "certifications" in page
            assert "infrastructure_highlights" in page
            assert "contact" in page
            assert len(page["sections"]) > 0
        finally:
            db.close()

    def test_certifications(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            page = sp.get_public_security_page(db, ws.id)
            certs = page["certifications"]
            assert len(certs) >= 3
            assert any(c["name"] == "SOC 2 Type II" for c in certs)
        finally:
            db.close()

    def test_infrastructure_highlights(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            page = sp.get_public_security_page(db, ws.id)
            highlights = page["infrastructure_highlights"]
            assert len(highlights) >= 5
            assert any("AES-256" in h for h in highlights)
        finally:
            db.close()

    def test_section_items_have_frameworks(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            faq_svc.seed_defaults(db, ws.id)
            db.commit()
            page = sp.get_public_security_page(db, ws.id)
            for section in page["sections"]:
                for item in section["items"]:
                    assert "question" in item
                    assert "answer" in item
                    assert "frameworks" in item
        finally:
            db.close()


class TestSecurityPageAPI:
    def test_get_page(self, admin_client):
        r = admin_client.get("/api/security-page")
        assert r.status_code == 200
        data = r.json()
        assert "title" in data
        assert "sections" in data
        assert "certifications" in data

    def test_editor_can_access(self, editor_client):
        r = editor_client.get("/api/security-page")
        assert r.status_code == 200
