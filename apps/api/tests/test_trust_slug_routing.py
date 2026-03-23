"""Tests for slug-based trust request routing and workspace resolution."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.api.routes.trust_requests import resolve_workspace_for_trust_request


client = TestClient(app)


class TestResolveWorkspaceSlugPriority:
    """Slug should be primary resolution method."""

    def test_slug_resolves_first(self):
        db = MagicMock()
        ws = MagicMock()
        ws.id = 5
        db.query.return_value.filter.return_value.first.return_value = ws

        wid, method = resolve_workspace_for_trust_request(db, workspace_slug="acme")
        assert wid == 5
        assert method == "slug"

    def test_slug_takes_priority_over_explicit_id(self):
        db = MagicMock()
        ws = MagicMock()
        ws.id = 5
        db.query.return_value.filter.return_value.first.return_value = ws

        wid, method = resolve_workspace_for_trust_request(
            db, workspace_id=99, workspace_slug="acme"
        )
        assert wid == 5
        assert method == "slug"

    def test_invalid_slug_returns_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            resolve_workspace_for_trust_request(db, workspace_slug="nonexistent")
        assert exc_info.value.status_code == 404
        assert "slug" in exc_info.value.detail.lower()

    def test_explicit_id_works_when_no_slug(self):
        db = MagicMock()
        ws = MagicMock()
        ws.id = 10
        db.query.return_value.filter.return_value.first.return_value = ws

        wid, method = resolve_workspace_for_trust_request(db, workspace_id=10)
        assert wid == 10
        assert method == "explicit_id"

    def test_invalid_id_returns_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            resolve_workspace_for_trust_request(db, workspace_id=999)
        assert exc_info.value.status_code == 404


class TestProductionNoDefaultFallback:
    """In production, no slug + no id should fail, not silently default."""

    @patch("app.core.config.get_settings")
    def test_production_fails_without_slug_or_id(self, mock_settings):
        settings = MagicMock()
        settings.app_env = "production"
        mock_settings.return_value = settings

        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            resolve_workspace_for_trust_request(db)
        assert exc_info.value.status_code == 400
        assert "slug" in exc_info.value.detail.lower()

    @patch("app.core.config.get_settings")
    def test_dev_falls_back_to_default(self, mock_settings):
        settings = MagicMock()
        settings.app_env = "development"
        mock_settings.return_value = settings

        db = MagicMock()
        ws = MagicMock()
        ws.id = 1
        db.query.return_value.filter.return_value.first.return_value = ws

        wid, method = resolve_workspace_for_trust_request(db)
        assert wid == 1
        assert method == "default_dev"


class TestWorkspaceBySlugEndpoint:
    """Test GET /api/workspaces/by-slug/{slug}."""

    @pytest.fixture(autouse=True)
    def _mock_db(self):
        from app.core.database import get_db

        mock_session = MagicMock()

        def _get_db():
            yield mock_session

        app.dependency_overrides[get_db] = _get_db
        yield mock_session
        app.dependency_overrides.pop(get_db, None)

    def test_valid_slug_returns_workspace_info(self, _mock_db):
        ws = MagicMock()
        ws.id = 1
        ws.name = "Acme Corp"
        ws.slug = "acme"
        _mock_db.query.return_value.filter.return_value.first.return_value = ws

        r = client.get("/api/workspaces/by-slug/acme")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == 1
        assert data["name"] == "Acme Corp"
        assert data["slug"] == "acme"

    def test_invalid_slug_returns_404(self, _mock_db):
        _mock_db.query.return_value.filter.return_value.first.return_value = None

        r = client.get("/api/workspaces/by-slug/nonexistent")
        assert r.status_code == 404

    def test_no_sensitive_fields_exposed(self, _mock_db):
        ws = MagicMock()
        ws.id = 1
        ws.name = "Acme Corp"
        ws.slug = "acme"
        ws.mfa_required = True
        ws.session_max_age_seconds = 3600
        _mock_db.query.return_value.filter.return_value.first.return_value = ws

        r = client.get("/api/workspaces/by-slug/acme")
        assert r.status_code == 200
        data = r.json()
        assert "mfa_required" not in data
        assert "session_max_age_seconds" not in data
        assert set(data.keys()) == {"id", "name", "slug"}


class TestPublicSubmissionWithSlug:
    """Test POST /api/trust-requests/submit with workspace_slug."""

    @pytest.fixture(autouse=True)
    def _mock_db(self):
        from app.core.database import get_db

        mock_session = MagicMock()

        def _get_db():
            yield mock_session

        app.dependency_overrides[get_db] = _get_db
        yield mock_session
        app.dependency_overrides.pop(get_db, None)

    def test_submit_with_slug_resolves(self, _mock_db):
        ws = MagicMock()
        ws.id = 2

        mock_req = MagicMock()
        mock_req.id = 100
        mock_req.workspace_id = 2
        mock_req.display_id = "TR-000100"
        mock_req.requester_email = "user@test.com"
        mock_req.requester_name = "Test"
        mock_req.subject = "Test"
        mock_req.message = "Hello"
        mock_req.frameworks_json = '["Other"]'
        mock_req.subject_areas_json = '["Other"]'
        mock_req.status = "new"
        mock_req.attachment_filename = None
        mock_req.attachment_storage_key = None
        mock_req.attachment_size = None
        mock_req.submitted_host = "localhost"
        mock_req.submitted_path = ""
        mock_req.resolution_method = "slug"
        mock_req.assignee_id = None
        mock_req.created_at = None
        mock_req.deleted_at = None

        _mock_db.query.return_value.filter.return_value.first.return_value = ws

        with patch("app.api.routes.trust_requests.TrustRequest", return_value=mock_req):
            r = client.post(
                "/api/trust-requests/submit",
                data={
                    "requester_email": "user@test.com",
                    "requester_name": "Test",
                    "subject": "Test",
                    "message": "Hello",
                    "workspace_slug": "acme",
                },
            )

        assert r.status_code == 200
        data = r.json()
        assert data["resolution_method"] == "slug"
        assert data["workspace_id"] == 2
