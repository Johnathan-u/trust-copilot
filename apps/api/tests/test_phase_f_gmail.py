"""Phase F — Gmail Integration: connect, labels, ingest, dedup, suggestions, permissions, isolation."""

import json

import pytest
from fastapi.testclient import TestClient


def _login_admin(client: TestClient) -> dict:
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200
    return r.json()


def _ensure_gmail_connected():
    from app.core.database import SessionLocal
    from app.models import GmailIntegration
    from app.services.gmail_service import encrypt_token
    db = SessionLocal()
    try:
        gi = db.query(GmailIntegration).filter(GmailIntegration.workspace_id == 1).first()
        if not gi:
            gi = GmailIntegration(workspace_id=1, access_token_encrypted=encrypt_token("ya29.test"), email_address="test@example.com", enabled=True)
            db.add(gi)
            db.commit()
            db.refresh(gi)
        return gi.id
    finally:
        db.close()


def _cleanup_gmail(workspace_id=1):
    from app.core.database import SessionLocal
    from app.models import GmailIngestLabel, GmailControlSuggestion, EvidenceItem
    db = SessionLocal()
    try:
        db.query(GmailControlSuggestion).filter(GmailControlSuggestion.workspace_id == workspace_id).delete()
        db.query(GmailIngestLabel).filter(GmailIngestLabel.workspace_id == workspace_id).delete()
        db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id, EvidenceItem.source_type == "gmail").delete()
        db.commit()
    finally:
        db.close()


def _get_audit(action, ws=1):
    from app.core.database import SessionLocal
    from app.models import AuditEvent
    db = SessionLocal()
    try:
        return db.query(AuditEvent).filter(AuditEvent.action == action, AuditEvent.workspace_id == ws).order_by(AuditEvent.occurred_at.desc()).limit(5).all()
    finally:
        db.close()


# ---- Connect / Disconnect ----

class TestGmailConnect:
    def test_connect(self, client: TestClient) -> None:
        _login_admin(client)
        from app.core.database import SessionLocal
        from app.models import GmailIntegration
        db = SessionLocal()
        db.query(GmailIntegration).filter(GmailIntegration.workspace_id == 1).delete()
        db.commit()
        db.close()
        r = client.post("/api/gmail/connect", json={"access_token": "ya29.test-token-long-enough"})
        assert r.status_code == 200
        assert r.json()["connected"] is True

    def test_status(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        r = client.get("/api/gmail/status")
        assert r.status_code == 200
        assert r.json()["connected"] is True

    def test_disconnect(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        r = client.delete("/api/gmail/disconnect")
        assert r.status_code == 200
        r2 = client.get("/api/gmail/status")
        assert r2.json()["connected"] is False
        _ensure_gmail_connected()

    def test_connect_audit(self, client: TestClient) -> None:
        _login_admin(client)
        from app.core.database import SessionLocal
        from app.models import GmailIntegration
        db = SessionLocal()
        db.query(GmailIntegration).filter(GmailIntegration.workspace_id == 1).delete()
        db.commit()
        db.close()
        client.post("/api/gmail/connect", json={"access_token": "ya29.audit-test-long"})
        events = _get_audit("gmail.connected")
        assert len(events) > 0

    def test_token_not_in_status(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        r = client.get("/api/gmail/status")
        assert "ya29" not in r.text


# ---- Labels ----

class TestGmailLabels:
    def test_add_label(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        r = client.post("/api/gmail/ingest/labels", json={"label_id": "Label_Test", "label_name": "Test"})
        assert r.status_code == 200
        assert r.json()["label_id"] == "Label_Test"

    def test_duplicate_label_rejected(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        client.post("/api/gmail/ingest/labels", json={"label_id": "Label_Dup"})
        r = client.post("/api/gmail/ingest/labels", json={"label_id": "Label_Dup"})
        assert r.status_code == 400

    def test_list_labels(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        client.post("/api/gmail/ingest/labels", json={"label_id": "Label_List", "label_name": "Listed"})
        r = client.get("/api/gmail/ingest/labels")
        assert r.status_code == 200
        assert any(l["label_id"] == "Label_List" for l in r.json()["labels"])

    def test_remove_label(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        r = client.post("/api/gmail/ingest/labels", json={"label_id": "Label_Del"})
        lid = r.json()["id"]
        r2 = client.delete(f"/api/gmail/ingest/labels/{lid}")
        assert r2.status_code == 200

    def test_label_audit(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        client.post("/api/gmail/ingest/labels", json={"label_id": "Label_Audit"})
        events = _get_audit("gmail.label_approved")
        assert len(events) > 0


# ---- Ingest ----

class TestGmailIngest:
    def test_run_ingest(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        r = client.post("/api/gmail/ingest/labels", json={"label_id": "Label_Ingest", "label_name": "Ingest"})
        lid = r.json()["id"]
        r2 = client.post(f"/api/gmail/ingest/run/{lid}?limit=3")
        assert r2.status_code == 200
        d = r2.json()
        assert d["ingested"] >= 1

    def test_evidence_has_source_gmail(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        r = client.post("/api/gmail/ingest/labels", json={"label_id": "Label_Src"})
        lid = r.json()["id"]
        client.post(f"/api/gmail/ingest/run/{lid}?limit=2")
        r2 = client.get("/api/gmail/ingest/evidence")
        assert r2.status_code == 200
        ev = r2.json()["evidence"]
        assert len(ev) > 0
        meta = ev[0].get("source_metadata", {})
        assert "gmail_message_id" in meta

    def test_attachments_ingested(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        r = client.post("/api/gmail/ingest/labels", json={"label_id": "Label_Att"})
        lid = r.json()["id"]
        r2 = client.post(f"/api/gmail/ingest/run/{lid}?limit=3")
        d = r2.json()
        assert d["attachments"] >= 1

    def test_evidence_audit(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        r = client.post("/api/gmail/ingest/labels", json={"label_id": "Label_EAudit"})
        lid = r.json()["id"]
        client.post(f"/api/gmail/ingest/run/{lid}?limit=1")
        events = _get_audit("gmail.evidence_ingested")
        assert len(events) > 0

    def test_unapproved_label_rejected(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        r = client.post("/api/gmail/ingest/run/99999")
        assert r.status_code == 404


# ---- Dedup ----

class TestGmailDedup:
    def test_duplicate_not_ingested(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        from app.core.database import SessionLocal
        from app.services.gmail_ingest_service import ingest_email
        db = SessionLocal()
        try:
            msg = {"id": "dedup_msg_1", "threadId": "t1", "subject": "Test", "from": "a@b.com", "date": "2026-01-01", "snippet": "Test", "attachments": []}
            r1 = ingest_email(db, 1, "L1", msg)
            assert r1["email_evidence_id"] is not None
            r2 = ingest_email(db, 1, "L1", msg)
            assert r2["email_evidence_id"] is None
        finally:
            db.close()


# ---- Permissions ----

class TestGmailPermissions:
    def test_unauthenticated_rejected(self, client: TestClient) -> None:
        r = client.get("/api/gmail/status")
        assert r.status_code == 401

    def test_non_admin_rejected(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
        orig = mem.role
        mem.role = "editor"
        db.commit()
        db.close()
        try:
            client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
            r = client.post("/api/gmail/connect", json={"access_token": "x" * 20})
            assert r.status_code == 403
        finally:
            db2 = SessionLocal()
            m2 = db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
            m2.role = orig
            db2.commit()
            db2.close()

    def test_cross_workspace_isolation(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_gmail_connected()
        _cleanup_gmail()
        _cleanup_gmail(2)
        client.post("/api/gmail/ingest/labels", json={"label_id": "Label_WS1"})
        from app.core.database import SessionLocal
        from app.models import GmailIngestLabel
        db = SessionLocal()
        try:
            ws1 = db.query(GmailIngestLabel).filter(GmailIngestLabel.workspace_id == 1, GmailIngestLabel.label_id == "Label_WS1").first()
            assert ws1 is not None
            ws2 = db.query(GmailIngestLabel).filter(GmailIngestLabel.workspace_id == 2, GmailIngestLabel.label_id == "Label_WS1").first()
            assert ws2 is None
        finally:
            db.close()
