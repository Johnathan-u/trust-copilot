"""Multi-tenant isolation tests — P0 cross-tenant vulnerability verification.

Every test creates resources in workspace 1 (as admin) then attempts to access
them from workspace 2 (after switching workspace), verifying 404/403.
"""

import pytest
from fastapi.testclient import TestClient


def _login_admin_ws1(client: TestClient) -> dict:
    """Log in as admin in workspace 1."""
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1
        ).first()
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200
    return r.json()


def _switch_to_ws2(client: TestClient) -> None:
    """Switch session to workspace 2. Demo user is member of both (from conftest)."""
    r = client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    assert r.status_code == 200


def _switch_to_ws1(client: TestClient) -> None:
    """Switch session back to workspace 1."""
    r = client.post("/api/auth/switch-workspace", json={"workspace_id": 1})
    assert r.status_code == 200


def _ensure_control_in_ws1(db) -> int:
    from app.models import Control
    c = db.query(Control).filter(Control.workspace_id == 1).first()
    if c:
        return c.id
    c = Control(workspace_id=1, framework="SOC2", control_id="CC1.1", name="Test Control", status="in_review")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c.id


def _ensure_control_in_ws2(db) -> int:
    from app.models import Control
    c = db.query(Control).filter(Control.workspace_id == 2).first()
    if c:
        return c.id
    c = Control(workspace_id=2, framework="SOC2", control_id="CC2.1", name="WS2 Control", status="in_review")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c.id


def _ensure_document_in_ws2(db) -> int:
    from app.models import Document
    d = db.query(Document).filter(Document.workspace_id == 2).first()
    if d:
        return d.id
    d = Document(workspace_id=2, filename="ws2_secret.pdf", storage_key="ws2/secret.pdf")
    db.add(d)
    db.commit()
    db.refresh(d)
    return d.id


def _ensure_trust_article_ws1(db, published=1, is_policy=False) -> int:
    from app.models import TrustArticle
    slug = f"mt-test-{'pub' if published else 'priv'}-{'pol' if is_policy else 'art'}"
    a = db.query(TrustArticle).filter(TrustArticle.slug == slug).first()
    if a:
        return a.id
    a = TrustArticle(
        workspace_id=1, slug=slug, title=f"MT Test {slug}",
        content="test", published=published, is_policy=is_policy,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a.id


def _ensure_trust_article_ws2(db) -> int:
    from app.models import TrustArticle
    a = db.query(TrustArticle).filter(TrustArticle.workspace_id == 2).first()
    if a:
        return a.id
    a = TrustArticle(
        workspace_id=2, slug="ws2-private-art", title="WS2 Private",
        content="secret", published=0, is_policy=False,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a.id


# ---------------------------------------------------------------------------
# F-01: controls list_controls — session workspace only
# ---------------------------------------------------------------------------

class TestControlsListIsolation:
    def test_list_controls_returns_own_workspace_only(self, client: TestClient) -> None:
        """Controls list must return only current workspace's controls."""
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            _ensure_control_in_ws1(db)
            _ensure_control_in_ws2(db)
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.get("/api/controls/")
        assert r.status_code == 200
        for c in r.json():
            assert c["workspace_id"] == 1

    def test_list_controls_ignores_workspace_id_param(self, client: TestClient) -> None:
        """Even if workspace_id query param is sent, it must be ignored (uses session)."""
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            _ensure_control_in_ws2(db)
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.get("/api/controls/?workspace_id=2")
        assert r.status_code == 200
        for c in r.json():
            assert c["workspace_id"] == 1

    def test_switch_workspace_shows_correct_controls(self, client: TestClient) -> None:
        """After switching to WS2, list should show WS2 controls."""
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            _ensure_control_in_ws2(db)
        finally:
            db.close()

        _login_admin_ws1(client)
        _switch_to_ws2(client)
        r = client.get("/api/controls/")
        assert r.status_code == 200
        for c in r.json():
            assert c["workspace_id"] == 2
        _switch_to_ws1(client)


# ---------------------------------------------------------------------------
# F-02: vendor_requests list — session workspace only
# ---------------------------------------------------------------------------

class TestVendorRequestsListIsolation:
    def test_list_vendor_requests_returns_own_workspace_only(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import VendorRequest
        db = SessionLocal()
        try:
            existing = db.query(VendorRequest).filter(VendorRequest.workspace_id == 2).first()
            if not existing:
                db.add(VendorRequest(workspace_id=2, vendor_email="vendor@other.com", status="sent", link_token="tok123"))
                db.commit()
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.get("/api/vendor-requests/")
        assert r.status_code == 200
        for v in r.json():
            assert v["workspace_id"] == 1

    def test_list_vendor_requests_ignores_workspace_id_param(self, client: TestClient) -> None:
        _login_admin_ws1(client)
        r = client.get("/api/vendor-requests/?workspace_id=2")
        assert r.status_code == 200
        for v in r.json():
            assert v["workspace_id"] == 1


# ---------------------------------------------------------------------------
# F-03: trust_articles get — workspace gating
# ---------------------------------------------------------------------------

class TestTrustArticleGetIsolation:
    def test_authenticated_cannot_read_other_workspace_article(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            art_id = _ensure_trust_article_ws2(db)
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.get(f"/api/trust-articles/{art_id}")
        assert r.status_code == 404

    def test_unauthenticated_cannot_read_unpublished_article(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            art_id = _ensure_trust_article_ws1(db, published=0)
        finally:
            db.close()

        fresh = TestClient(client.app, base_url="http://localhost", headers={"Origin": "http://localhost", "Referer": "http://localhost/"})
        r = fresh.get(f"/api/trust-articles/{art_id}")
        assert r.status_code == 404

    def test_authenticated_can_read_own_workspace_article(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            art_id = _ensure_trust_article_ws1(db, published=1)
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.get(f"/api/trust-articles/{art_id}")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# F-04: acknowledge_policy — workspace check
# ---------------------------------------------------------------------------

class TestAcknowledgePolicyIsolation:
    def test_cannot_acknowledge_other_workspace_policy(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import TrustArticle
        db = SessionLocal()
        try:
            a = db.query(TrustArticle).filter(TrustArticle.workspace_id == 2, TrustArticle.is_policy.is_(True)).first()
            if not a:
                a = TrustArticle(workspace_id=2, slug="ws2-policy-mt", title="WS2 Policy", content="secret", published=1, is_policy=True)
                db.add(a)
                db.commit()
                db.refresh(a)
            art_id = a.id
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.post(f"/api/trust-articles/{art_id}/acknowledge")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# F-05: trust_requests public submit — workspace validation
# ---------------------------------------------------------------------------

class TestTrustRequestPublicSubmit:
    def test_submit_to_nonexistent_workspace_returns_404(self, client: TestClient) -> None:
        r = client.post("/api/trust-requests/", json={
            "requester_email": "attacker@evil.com",
            "message": "give me data",
            "workspace_id": 99999,
        })
        assert r.status_code == 404

    def test_submit_to_valid_workspace_succeeds(self, client: TestClient) -> None:
        r = client.post("/api/trust-requests/", json={
            "requester_email": "legit@example.com",
            "message": "requesting info",
            "workspace_id": 1,
        })
        assert r.status_code == 200

    def test_submit_with_attachment_to_nonexistent_workspace_returns_404(self, client: TestClient) -> None:
        r = client.post("/api/trust-requests/submit", data={
            "requester_email": "attacker@evil.com",
            "message": "give me data",
            "workspace_id": 99999,
        })
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# F-06: attach_evidence — cross-workspace resource validation
# ---------------------------------------------------------------------------

class TestAttachEvidenceIsolation:
    def test_cannot_attach_other_workspace_document(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            ctrl_id = _ensure_control_in_ws1(db)
            doc_id = _ensure_document_in_ws2(db)
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.post(f"/api/controls/{ctrl_id}/evidence", json={"document_id": doc_id})
        assert r.status_code == 404
        assert "not found in this workspace" in r.json()["detail"]

    def test_cannot_attach_other_workspace_trust_article(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            ctrl_id = _ensure_control_in_ws1(db)
            art_id = _ensure_trust_article_ws2(db)
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.post(f"/api/controls/{ctrl_id}/evidence", json={"trust_article_id": art_id})
        assert r.status_code == 404
        assert "not found in this workspace" in r.json()["detail"]

    def test_cannot_attach_other_workspace_export_record(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import ExportRecord
        db = SessionLocal()
        try:
            ctrl_id = _ensure_control_in_ws1(db)
            er = db.query(ExportRecord).filter(ExportRecord.workspace_id == 2).first()
            if not er:
                er = ExportRecord(workspace_id=2, questionnaire_id=None, filename="ws2_export.xlsx", storage_key="ws2/export.xlsx", status="completed")
                db.add(er)
                db.commit()
                db.refresh(er)
            er_id = er.id
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.post(f"/api/controls/{ctrl_id}/evidence", json={"export_record_id": er_id})
        assert r.status_code == 404
        assert "not found in this workspace" in r.json()["detail"]

    def test_can_attach_same_workspace_document(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import Document, ControlEvidence
        db = SessionLocal()
        try:
            ctrl_id = _ensure_control_in_ws1(db)
            d = db.query(Document).filter(Document.workspace_id == 1).first()
            if not d:
                d = Document(workspace_id=1, filename="ws1_doc.pdf", storage_key="ws1/doc.pdf")
                db.add(d)
                db.commit()
                db.refresh(d)
            doc_id = d.id
            db.query(ControlEvidence).filter(
                ControlEvidence.control_id == ctrl_id, ControlEvidence.document_id == doc_id
            ).delete()
            db.commit()
        finally:
            db.close()

        _login_admin_ws1(client)
        r = client.post(f"/api/controls/{ctrl_id}/evidence", json={"document_id": doc_id})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# F-07: trust_articles list — no unauthenticated workspace enumeration
# ---------------------------------------------------------------------------

class TestTrustArticleListIsolation:
    def test_authenticated_list_ignores_workspace_id_param(self, client: TestClient) -> None:
        _login_admin_ws1(client)
        r = client.get("/api/trust-articles/?workspace_id=2")
        assert r.status_code == 200
        for a in r.json():
            assert a["workspace_id"] == 1

    def test_unauthenticated_list_rejects_nonexistent_workspace(self, client: TestClient) -> None:
        fresh = TestClient(client.app, base_url="http://localhost", headers={"Origin": "http://localhost", "Referer": "http://localhost/"})
        r = fresh.get("/api/trust-articles/?published_only=true&workspace_id=99999")
        assert r.status_code == 404

    def test_unauthenticated_list_without_workspace_returns_401(self, client: TestClient) -> None:
        fresh = TestClient(client.app, base_url="http://localhost", headers={"Origin": "http://localhost", "Referer": "http://localhost/"})
        r = fresh.get("/api/trust-articles/")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Cumulative: policy acknowledgment workspace scoping
# ---------------------------------------------------------------------------

class TestPolicyAcknowledgmentScoping:
    def test_acknowledgments_scoped_to_workspace(self, client: TestClient) -> None:
        """list_my_policy_acknowledgments should only return articles from current workspace."""
        _login_admin_ws1(client)
        r = client.get("/api/trust-articles/policy-acknowledgments")
        assert r.status_code == 200
        data = r.json()
        assert "acknowledged_article_ids" in data
