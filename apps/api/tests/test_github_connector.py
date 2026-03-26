"""Tests for GitHub connector (P1-23, P1-24, P1-25)."""

import pytest
from app.services import github_collector_service as gh


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


class TestGitHubCollectorService:
    def test_collect_repos(self):
        result = gh.collect_repos("test-org")
        assert result["source"] == "github.repos"
        assert len(result["findings"]) >= 3

    def test_collect_access(self):
        result = gh.collect_access()
        assert result["source"] == "github.access"

    def test_collect_protection(self):
        result = gh.collect_branch_protection()
        assert result["source"] == "github.protection"
        assert len(result["findings"]) >= 4

    def test_full_sync(self):
        result = gh.run_github_sync(1, "test-org")
        assert result["total_findings"] >= 10


class TestGitHubConnectorAPI:
    def test_repos(self, admin_client):
        r = admin_client.get("/api/connectors/github/repos")
        assert r.status_code == 200

    def test_access(self, admin_client):
        r = admin_client.get("/api/connectors/github/access")
        assert r.status_code == 200

    def test_protection(self, admin_client):
        r = admin_client.get("/api/connectors/github/protection")
        assert r.status_code == 200

    def test_sync(self, admin_client):
        r = admin_client.post("/api/connectors/github/sync")
        assert r.status_code == 200
        assert r.json()["total_findings"] >= 10

    def test_editor_cannot_sync(self, editor_client):
        r = editor_client.post("/api/connectors/github/sync")
        assert r.status_code == 403
