"""Tests for connector setup wizard (P1-15)."""

import pytest
from app.services import connector_wizard_service as svc


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


class TestConnectorWizardService:
    def test_get_catalog(self):
        catalog = svc.get_catalog()
        assert len(catalog) >= 8
        types = [c["connector_type"] for c in catalog]
        assert "aws" in types
        assert "github" in types
        assert "google_workspace" in types

    def test_get_connector_details(self):
        details = svc.get_connector_details("aws")
        assert details["display_name"] == "Amazon Web Services"
        assert "permissions_required" in details
        assert "data_collected" in details
        assert "data_not_collected" in details
        assert "setup_steps" in details

    def test_unknown_connector(self):
        assert svc.get_connector_details("unknown") is None

    def test_start_setup(self, db_session):
        from app.models.workspace import Workspace

        ws = db_session.query(Workspace).first()
        # A previous test may have committed this source as enabled. Disable is a no-op
        # error when the row is absent, and it clears enabled when the row exists.
        svc.disable_connector(db_session, ws.id, "aws")
        result = svc.start_setup(db_session, ws.id, "aws")
        db_session.commit()
        assert "error" not in result
        assert result["connector_type"] == "aws"
        assert result["status"] == "setup_pending"
        assert "setup_steps" in result

    def test_validate_setup(self, db_session):
        from app.models.workspace import Workspace

        ws = db_session.query(Workspace).first()
        svc.start_setup(db_session, ws.id, "github")
        db_session.commit()
        result = svc.validate_setup(db_session, ws.id, "github")
        db_session.commit()
        assert result["status"] == "not_validated"
        assert result["enabled"] is False
        assert "error" not in result

    def test_disable_connector(self, db_session):
        from app.models.workspace import Workspace

        ws = db_session.query(Workspace).first()
        svc.start_setup(db_session, ws.id, "okta")
        svc.validate_setup(db_session, ws.id, "okta")
        db_session.commit()
        result = svc.disable_connector(db_session, ws.id, "okta")
        db_session.commit()
        assert result["status"] == "disabled"
        assert result["enabled"] is False

    def test_start_unknown_connector(self, db_session):
        from app.models.workspace import Workspace

        ws = db_session.query(Workspace).first()
        result = svc.start_setup(db_session, ws.id, "nonexistent")
        assert "error" in result


class TestConnectorWizardAPI:
    def test_catalog(self, admin_client):
        r = admin_client.get("/api/connector-wizard/catalog")
        assert r.status_code == 200
        assert "connectors" in r.json()
        assert len(r.json()["connectors"]) >= 8

    def test_connector_details(self, admin_client):
        r = admin_client.get("/api/connector-wizard/catalog/aws")
        assert r.status_code == 200
        assert r.json()["display_name"] == "Amazon Web Services"

    def test_unknown_connector(self, admin_client):
        r = admin_client.get("/api/connector-wizard/catalog/unknown")
        assert r.status_code == 404

    def test_start_setup(self, admin_client):
        # Root cause of the previous 400: test_connector_health commits azure with
        # enabled=True, and start_setup's existing contract rejects an enabled
        # connector. Validate no longer enables a connector without a successful
        # probe, so this test restores the not-enabled row itself, then checks
        # that enabling it again still returns the same 400.
        admin_client.post("/api/connector-wizard/disable", json={"connector_type": "azure"})
        started = admin_client.post("/api/connector-wizard/start", json={"connector_type": "azure"})
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "setup_pending"
        enabled = admin_client.patch("/api/sources/azure", json={"enabled": True})
        assert enabled.status_code == 200, enabled.text
        again = admin_client.post("/api/connector-wizard/start", json={"connector_type": "azure"})
        assert again.status_code == 400
        assert again.json()["detail"] == "Connector 'azure' is already enabled"

    def test_validate(self, admin_client):
        admin_client.post("/api/connector-wizard/start", json={"connector_type": "gitlab"})
        r = admin_client.post("/api/connector-wizard/validate", json={"connector_type": "gitlab"})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert r.json()["status"] == "not_validated"

    def test_editor_cannot_start(self, editor_client):
        r = editor_client.post("/api/connector-wizard/start", json={"connector_type": "aws"})
        assert r.status_code == 403
