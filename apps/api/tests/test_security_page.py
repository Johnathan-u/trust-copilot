"""Tests for public security page (P0-82)."""

import secrets

import pytest
from sqlalchemy import text

from app.models.security_faq import SecurityFAQ
from app.models.workspace import Workspace
from app.services import security_page_service as sp
from app.services import security_faq_service as faq_svc


@pytest.fixture
def page_workspace(db_session):
    tables = ("workspaces", "security_faq", "security_faq_sources", "security_faq_revisions")
    before = {t: db_session.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
    workspace = Workspace(
        id=900_000_000 + secrets.randbelow(100_000_000),
        name="Synthetic security page",
        slug=f"security-page-{secrets.token_hex(8)}",
    )
    db_session.add(workspace)
    db_session.commit()
    workspace_id = workspace.id
    try:
        yield db_session, workspace_id
    finally:
        db_session.rollback()
        db_session.query(SecurityFAQ).filter_by(workspace_id=workspace_id).delete(
            synchronize_session=False
        )
        db_session.query(Workspace).filter_by(id=workspace_id).delete(synchronize_session=False)
        db_session.commit()
        after = {t: db_session.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
        assert after == before


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
    def test_page_structure(self, page_workspace):
        db, workspace_id = page_workspace
        faq_svc.seed_defaults(db, workspace_id)
        db.commit()
        page = sp.get_public_security_page(db, workspace_id)
        assert page["title"] == "Security & Data Handling"
        assert "sections" in page
        assert "certifications" in page
        assert "infrastructure_highlights" in page
        assert "contact" in page
        assert page["sections"] == []

    def test_certifications(self, page_workspace):
        db, workspace_id = page_workspace
        page = sp.get_public_security_page(db, workspace_id)
        certs = page["certifications"]
        assert len(certs) >= 3
        assert any(c["name"] == "SOC 2 Type II" for c in certs)

    def test_infrastructure_highlights(self, page_workspace):
        db, workspace_id = page_workspace
        page = sp.get_public_security_page(db, workspace_id)
        highlights = page["infrastructure_highlights"]
        assert len(highlights) >= 5
        assert any("AES-256" in h for h in highlights)

    def test_unreviewed_templates_have_no_public_items(self, page_workspace):
        db, workspace_id = page_workspace
        assert faq_svc.seed_defaults(db, workspace_id) > 0
        db.commit()
        assert faq_svc.list_faqs(db, workspace_id)
        # The reviewed-publication domain test covers the positive item shape.
        assert sp.get_public_security_page(db, workspace_id)["sections"] == []


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
