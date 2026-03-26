"""Tests for cloud connector packs (P2-103 GCP, P2-104 Azure, P2-105 GitLab, P2-106 Okta, P2-107 HRIS)."""

import pytest
from app.services import cloud_connector_service as cc


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


class TestCloudConnectorService:
    def test_gcp(self):
        result = cc.collect_gcp("test-project")
        assert result["source"] == "gcp"
        assert len(result["findings"]) >= 4

    def test_azure(self):
        result = cc.collect_azure("test-tenant")
        assert result["source"] == "azure"
        assert len(result["findings"]) >= 4

    def test_gitlab(self):
        result = cc.collect_gitlab("test-group")
        assert result["source"] == "gitlab"
        assert len(result["findings"]) >= 4

    def test_okta(self):
        result = cc.collect_okta("test.okta.com")
        assert result["source"] == "okta"
        assert len(result["findings"]) >= 4

    def test_hris(self):
        result = cc.collect_hris("BambooHR")
        assert result["source"] == "hris"
        assert len(result["findings"]) >= 3

    def test_sync_connector(self):
        result = cc.run_connector_sync(1, "gcp")
        assert result["connector"] == "gcp"
        assert result["workspace_id"] == 1

    def test_unknown_connector(self):
        result = cc.run_connector_sync(1, "unknown")
        assert "error" in result


class TestCloudConnectorAPI:
    def test_gcp(self, admin_client):
        r = admin_client.get("/api/connectors/cloud/gcp")
        assert r.status_code == 200

    def test_azure(self, admin_client):
        r = admin_client.get("/api/connectors/cloud/azure")
        assert r.status_code == 200

    def test_gitlab(self, admin_client):
        r = admin_client.get("/api/connectors/cloud/gitlab")
        assert r.status_code == 200

    def test_okta(self, admin_client):
        r = admin_client.get("/api/connectors/cloud/okta")
        assert r.status_code == 200

    def test_hris(self, admin_client):
        r = admin_client.get("/api/connectors/cloud/hris")
        assert r.status_code == 200

    def test_sync(self, admin_client):
        r = admin_client.post("/api/connectors/cloud/sync/gcp")
        assert r.status_code == 200

    def test_editor_cannot_sync(self, editor_client):
        r = editor_client.post("/api/connectors/cloud/sync/gcp")
        assert r.status_code == 403

    def test_unknown_connector_rejected(self, admin_client):
        r = admin_client.post("/api/connectors/cloud/sync/unknown")
        assert r.status_code == 400
