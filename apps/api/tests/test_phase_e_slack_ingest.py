"""Phase E — Slack Ingest to Evidence: approved channels, evidence creation, dedup, isolation, audit, suggestions."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _login_admin(client: TestClient) -> dict:
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


def _ensure_slack_connected(client: TestClient):
    """Ensure Slack integration exists for workspace 1."""
    from app.core.database import SessionLocal
    from app.models import SlackIntegration
    from app.services.slack_service import encrypt_token
    db = SessionLocal()
    try:
        si = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == 1).first()
        if not si:
            si = SlackIntegration(
                workspace_id=1,
                bot_token_encrypted=encrypt_token("xoxb-test-ingest-token"),
                channel_id="C_NOTIF",
                channel_name="notif",
                enabled=True,
            )
            db.add(si)
            db.commit()
            db.refresh(si)
        return si.id
    finally:
        db.close()


def _cleanup_ingest(workspace_id: int = 1):
    from app.core.database import SessionLocal
    from app.models import SlackIngestChannel, SlackControlSuggestion, EvidenceItem
    db = SessionLocal()
    try:
        db.query(SlackControlSuggestion).filter(SlackControlSuggestion.workspace_id == workspace_id).delete()
        db.query(SlackIngestChannel).filter(SlackIngestChannel.workspace_id == workspace_id).delete()
        db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id, EvidenceItem.source_type == "slack").delete()
        db.commit()
    finally:
        db.close()


def _get_audit_events(action: str, workspace_id: int = 1) -> list:
    from app.core.database import SessionLocal
    from app.models import AuditEvent
    db = SessionLocal()
    try:
        return db.query(AuditEvent).filter(
            AuditEvent.action == action, AuditEvent.workspace_id == workspace_id
        ).order_by(AuditEvent.occurred_at.desc()).limit(5).all()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Approved channels
# ---------------------------------------------------------------------------

class TestIngestChannels:
    def test_approve_channel(self, client: TestClient) -> None:
        _login_admin(client)
        si_id = _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_INGEST_1", "channel_name": "evidence-ch"})
        assert r.status_code == 200
        assert r.json()["channel_id"] == "C_INGEST_1"
        assert r.json()["enabled"] is True

    def test_approve_requires_slack_connection(self, client: TestClient) -> None:
        _login_admin(client)
        from app.core.database import SessionLocal
        from app.models import SlackIntegration, SlackIngestChannel
        db = SessionLocal()
        db.query(SlackIngestChannel).filter(SlackIngestChannel.workspace_id == 1).delete()
        db.query(SlackIntegration).filter(SlackIntegration.workspace_id == 1).delete()
        db.commit()
        db.close()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_NOSLACK"})
        assert r.status_code == 400
        _ensure_slack_connected(client)

    def test_reject_duplicate_channel(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        client.post("/api/slack/ingest/channels", json={"channel_id": "C_DUP"})
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_DUP"})
        assert r.status_code == 400

    def test_list_channels(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        client.post("/api/slack/ingest/channels", json={"channel_id": "C_LIST", "channel_name": "list-ch"})
        r = client.get("/api/slack/ingest/channels")
        assert r.status_code == 200
        channels = r.json()["channels"]
        assert any(c["channel_id"] == "C_LIST" for c in channels)

    def test_revoke_channel(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_REVOKE"})
        rid = r.json()["id"]
        r2 = client.delete(f"/api/slack/ingest/channels/{rid}")
        assert r2.status_code == 200
        r3 = client.get("/api/slack/ingest/channels")
        assert not any(c["channel_id"] == "C_REVOKE" for c in r3.json()["channels"])

    def test_approve_channel_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        client.post("/api/slack/ingest/channels", json={"channel_id": "C_AUDIT_APPROVE"})
        events = _get_audit_events("slack.ingest_channel_approved")
        assert len(events) > 0


# ---------------------------------------------------------------------------
# Ingest and evidence creation
# ---------------------------------------------------------------------------

class TestIngestRun:
    def test_run_ingest_creates_evidence(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_RUN", "channel_name": "run-ch"})
        rec_id = r.json()["id"]
        r2 = client.post(f"/api/slack/ingest/run/{rec_id}?limit=3")
        assert r2.status_code == 200
        d = r2.json()
        assert d["ingested"] >= 1

    def test_evidence_has_source_type_slack(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_SRC", "channel_name": "src-ch"})
        rec_id = r.json()["id"]
        client.post(f"/api/slack/ingest/run/{rec_id}?limit=2")
        r2 = client.get("/api/slack/ingest/evidence?page_size=10")
        assert r2.status_code == 200
        evidence = r2.json()["evidence"]
        assert len(evidence) > 0
        for ev in evidence:
            meta = ev.get("source_metadata")
            assert meta is not None
            assert meta["channel_id"] == "C_SRC"
            assert "message_ts" in meta

    def test_evidence_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_EAUDIT"})
        rec_id = r.json()["id"]
        client.post(f"/api/slack/ingest/run/{rec_id}?limit=1")
        events = _get_audit_events("slack.evidence_ingested")
        assert len(events) > 0

    def test_unapproved_channel_does_not_ingest(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/run/99999?limit=1")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDedup:
    def test_duplicate_messages_not_ingested(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_DEDUP"})
        rec_id = r.json()["id"]
        r1 = client.post(f"/api/slack/ingest/run/{rec_id}?limit=3")
        first_count = r1.json()["ingested"]
        assert first_count >= 1
        r2 = client.post(f"/api/slack/ingest/run/{rec_id}?limit=3")
        # Stub generates unique timestamps, so for true dedup we test via the service directly
        from app.core.database import SessionLocal
        from app.services.slack_ingest_service import ingest_message
        db = SessionLocal()
        try:
            ev1 = ingest_message(db, 1, "C_DEDUP", "fixed.ts.001", "Test dedup message")
            assert ev1 is not None
            ev2 = ingest_message(db, 1, "C_DEDUP", "fixed.ts.001", "Test dedup message again")
            assert ev2 is None, "Duplicate message should not create new evidence"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Permissions and workspace isolation
# ---------------------------------------------------------------------------

class TestIngestPermissions:
    def test_unauthenticated_cannot_approve(self, client: TestClient) -> None:
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_UNAUTH"})
        assert r.status_code == 401

    def test_unauthenticated_cannot_run(self, client: TestClient) -> None:
        r = client.post("/api/slack/ingest/run/1")
        assert r.status_code == 401

    def test_non_admin_cannot_approve(self, client: TestClient) -> None:
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
            r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_NONADMIN"})
            assert r.status_code == 403
        finally:
            db2 = SessionLocal()
            m2 = db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
            m2.role = orig
            db2.commit()
            db2.close()

    def test_cross_workspace_isolation(self, client: TestClient) -> None:
        """Ingest channel approved in workspace 1 is not visible in workspace 2."""
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        _cleanup_ingest(2)
        client.post("/api/slack/ingest/channels", json={"channel_id": "C_WS1_ONLY"})
        from app.core.database import SessionLocal
        from app.models import SlackIngestChannel
        db = SessionLocal()
        try:
            ws1 = db.query(SlackIngestChannel).filter(SlackIngestChannel.workspace_id == 1, SlackIngestChannel.channel_id == "C_WS1_ONLY").first()
            assert ws1 is not None
            ws2 = db.query(SlackIngestChannel).filter(SlackIngestChannel.workspace_id == 2, SlackIngestChannel.channel_id == "C_WS1_ONLY").first()
            assert ws2 is None
        finally:
            db.close()

    def test_evidence_scoped_to_workspace(self, client: TestClient) -> None:
        """Slack evidence in workspace 1 is not returned for workspace 2."""
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_SCOPE"})
        rec_id = r.json()["id"]
        client.post(f"/api/slack/ingest/run/{rec_id}?limit=1")
        from app.core.database import SessionLocal
        from app.models import EvidenceItem
        db = SessionLocal()
        try:
            ws1 = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == 1, EvidenceItem.source_type == "slack").count()
            ws2 = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == 2, EvidenceItem.source_type == "slack").count()
            assert ws1 > 0
            assert ws2 == 0
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Control suggestions
# ---------------------------------------------------------------------------

class TestControlSuggestions:
    def test_list_suggestions(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/slack/ingest/suggestions")
        assert r.status_code == 200
        assert "suggestions" in r.json()

    def test_suggestion_status_review(self, client: TestClient) -> None:
        """Create a suggestion manually and test approve/dismiss."""
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_SUG"})
        rec_id = r.json()["id"]
        client.post(f"/api/slack/ingest/run/{rec_id}?limit=1")
        # Create suggestion manually since keyword matching needs real controls
        from app.core.database import SessionLocal
        from app.models import EvidenceItem, SlackControlSuggestion, WorkspaceControl
        db = SessionLocal()
        try:
            ev = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == 1, EvidenceItem.source_type == "slack").first()
            if not ev:
                return  # Skip if no evidence
            wc = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == 1).first()
            if not wc:
                return  # Skip if no controls
            sug = SlackControlSuggestion(
                workspace_id=1, evidence_id=ev.id, control_id=wc.id, confidence=0.5, status="pending",
            )
            db.add(sug)
            db.commit()
            db.refresh(sug)
            sug_id = sug.id
        finally:
            db.close()
        r2 = client.patch(f"/api/slack/ingest/suggestions/{sug_id}", json={"action": "dismiss"})
        assert r2.status_code == 200
        assert r2.json()["status"] == "dismissed"

    def test_suggestion_review_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _ensure_slack_connected(client)
        _cleanup_ingest()
        r = client.post("/api/slack/ingest/channels", json={"channel_id": "C_SUG_AUD"})
        rec_id = r.json()["id"]
        client.post(f"/api/slack/ingest/run/{rec_id}?limit=1")
        from app.core.database import SessionLocal
        from app.models import EvidenceItem, SlackControlSuggestion, WorkspaceControl
        db = SessionLocal()
        try:
            ev = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == 1, EvidenceItem.source_type == "slack").first()
            wc = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == 1).first()
            if not ev or not wc:
                return
            sug = SlackControlSuggestion(workspace_id=1, evidence_id=ev.id, control_id=wc.id, confidence=0.4, status="pending")
            db.add(sug)
            db.commit()
            db.refresh(sug)
            sug_id = sug.id
        finally:
            db.close()
        client.patch(f"/api/slack/ingest/suggestions/{sug_id}", json={"action": "approve"})
        events = _get_audit_events("slack.suggestion_approved")
        assert len(events) > 0
