"""Tests for credential store (P0-08)."""

import pytest
from datetime import datetime, timedelta, timezone
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services import credential_store_service as cs


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


class TestCredentialStoreService:
    def _get_workspace(self, db):
        ws = db.query(Workspace).first()
        assert ws
        return ws

    def test_store_and_retrieve(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            cs.store_credential(db, ws.id, "slack", "bot_token", "xoxb-test-token-12345")
            db.commit()
            value = cs.get_credential(db, ws.id, "slack", "bot_token")
            assert value == "xoxb-test-token-12345"
        finally:
            db.close()

    def test_update_existing(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            cs.store_credential(db, ws.id, "github", "personal_token", "old-token")
            db.commit()
            cs.store_credential(db, ws.id, "github", "personal_token", "new-token")
            db.commit()
            value = cs.get_credential(db, ws.id, "github", "personal_token")
            assert value == "new-token"
        finally:
            db.close()

    def test_list_credentials(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            cs.store_credential(db, ws.id, "aws", "iam_key", "AKIATEST")
            db.commit()
            creds = cs.list_credentials(db, ws.id)
            assert isinstance(creds, list)
            assert any(c["source_type"] == "aws" for c in creds)
            assert all("value" not in c for c in creds)
        finally:
            db.close()

    def test_revoke_credential(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            cs.store_credential(db, ws.id, "okta", "api_token", "test-okta-token")
            db.commit()
            assert cs.revoke_credential(db, ws.id, "okta", "api_token")
            db.commit()
            value = cs.get_credential(db, ws.id, "okta", "api_token")
            assert value is None
        finally:
            db.close()

    def test_encryption_roundtrip(self):
        plaintext = "super-secret-api-key-999"
        encrypted = cs.encrypt(plaintext)
        assert encrypted != plaintext
        assert cs.decrypt(encrypted) == plaintext

    def test_rotation_due(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            cs.store_credential(db, ws.id, "test_rot", "token", "val", rotation_interval_days=1)
            db.commit()

            from app.models.credential_store import CredentialStore
            row = db.query(CredentialStore).filter(
                CredentialStore.workspace_id == ws.id,
                CredentialStore.source_type == "test_rot",
            ).first()
            row.last_rotated_at = datetime.now(timezone.utc) - timedelta(days=2)
            db.commit()

            due = cs.check_rotation_due(db, ws.id)
            assert any(c["source_type"] == "test_rot" for c in due)
        finally:
            db.close()

    def test_expiring_check(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            soon = datetime.now(timezone.utc) + timedelta(days=3)
            cs.store_credential(db, ws.id, "test_exp", "token", "val", expires_at=soon)
            db.commit()
            expiring = cs.check_expiring(db, ws.id, days_ahead=7)
            assert any(c["source_type"] == "test_exp" for c in expiring)
        finally:
            db.close()


class TestCredentialStoreAPI:
    def test_store_credential(self, admin_client):
        r = admin_client.post("/api/credentials", json={
            "source_type": "slack",
            "credential_type": "bot_token",
            "value": "xoxb-api-test",
        })
        assert r.status_code == 200
        assert r.json()["source_type"] == "slack"
        assert "value" not in r.json()

    def test_list_credentials(self, admin_client):
        admin_client.post("/api/credentials", json={
            "source_type": "api_test_list",
            "credential_type": "key",
            "value": "secret123",
        })
        r = admin_client.get("/api/credentials")
        assert r.status_code == 200
        assert "credentials" in r.json()

    def test_revoke_credential(self, admin_client):
        admin_client.post("/api/credentials", json={
            "source_type": "revoke_test",
            "credential_type": "token",
            "value": "to-revoke",
        })
        r = admin_client.delete("/api/credentials/revoke_test/token")
        assert r.status_code == 200
        assert r.json()["revoked"] is True

    def test_rotation_due_endpoint(self, admin_client):
        r = admin_client.get("/api/credentials/rotation-due")
        assert r.status_code == 200
        assert "credentials" in r.json()

    def test_expiring_endpoint(self, admin_client):
        r = admin_client.get("/api/credentials/expiring?days=30")
        assert r.status_code == 200
        assert "credentials" in r.json()

    def test_editor_cannot_store(self, editor_client):
        r = editor_client.post("/api/credentials", json={
            "source_type": "slack",
            "credential_type": "token",
            "value": "nope",
        })
        assert r.status_code == 403

    def test_empty_value_rejected(self, admin_client):
        r = admin_client.post("/api/credentials", json={
            "source_type": "empty",
            "credential_type": "key",
            "value": "  ",
        })
        assert r.status_code == 400
