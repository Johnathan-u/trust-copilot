"""Tests for trust request workspace routing and attachment handling."""
import io
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.models import Workspace


client = TestClient(app)


@pytest.fixture(autouse=True)
def _mock_db():
    """Override get_db for all tests."""
    from app.core.database import get_db

    mock_session = MagicMock()

    def _get_db():
        yield mock_session

    app.dependency_overrides[get_db] = _get_db
    yield mock_session
    app.dependency_overrides.pop(get_db, None)


class TestResolveWorkspace:
    """Tests for the workspace resolution logic in public trust submissions."""

    def test_explicit_workspace_id_resolves(self, _mock_db):
        ws = MagicMock()
        ws.id = 1
        _mock_db.query.return_value.filter.return_value.first.return_value = ws

        mock_req = MagicMock()
        mock_req.id = 99
        mock_req.workspace_id = 1
        mock_req.display_id = "TR-000099"
        mock_req.requester_email = "a@b.com"
        mock_req.requester_name = None
        mock_req.subject = None
        mock_req.message = "test"
        mock_req.frameworks_json = '["Other"]'
        mock_req.subject_areas_json = '["Other"]'
        mock_req.status = "new"
        mock_req.attachment_filename = None
        mock_req.attachment_storage_key = None
        mock_req.attachment_size = None
        mock_req.submitted_host = "localhost"
        mock_req.submitted_path = None
        mock_req.resolution_method = "explicit_id"
        mock_req.assignee_id = None
        mock_req.created_at = None
        mock_req.deleted_at = None

        _mock_db.add = MagicMock()
        _mock_db.flush = MagicMock()
        _mock_db.commit = MagicMock()
        _mock_db.refresh = MagicMock()

        with patch("app.api.routes.trust_requests.TrustRequest", return_value=mock_req):
            r = client.post("/api/trust-requests/", json={
                "requester_email": "a@b.com",
                "message": "test",
                "workspace_id": 1,
            })

        assert r.status_code == 200
        data = r.json()
        assert data["workspace_id"] == 1
        assert data["resolution_method"] == "explicit_id"

    def test_invalid_workspace_id_returns_404(self, _mock_db):
        _mock_db.query.return_value.filter.return_value.first.return_value = None

        r = client.post("/api/trust-requests/", json={
            "requester_email": "a@b.com",
            "message": "test",
            "workspace_id": 999,
        })
        assert r.status_code == 404

    def test_bad_slug_returns_404(self, _mock_db):
        _mock_db.query.return_value.filter.return_value.first.return_value = None

        r = client.post("/api/trust-requests/", json={
            "requester_email": "a@b.com",
            "message": "test",
            "workspace_slug": "nonexistent",
        })
        assert r.status_code == 404
        assert "slug" in r.json()["detail"].lower()


class TestResolveWorkspaceFunction:
    """Unit tests for resolve_workspace_for_trust_request."""

    def test_explicit_id_found(self):
        from app.api.routes.trust_requests import resolve_workspace_for_trust_request

        db = MagicMock()
        ws = MagicMock()
        ws.id = 5
        db.query.return_value.filter.return_value.first.return_value = ws

        wid, method = resolve_workspace_for_trust_request(db, workspace_id=5)
        assert wid == 5
        assert method == "explicit_id"

    def test_explicit_id_not_found(self):
        from app.api.routes.trust_requests import resolve_workspace_for_trust_request
        from fastapi import HTTPException

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            resolve_workspace_for_trust_request(db, workspace_id=999)
        assert exc_info.value.status_code == 404

    def test_slug_found(self):
        from app.api.routes.trust_requests import resolve_workspace_for_trust_request

        db = MagicMock()
        ws = MagicMock()
        ws.id = 3
        db.query.return_value.filter.return_value.first.return_value = ws

        wid, method = resolve_workspace_for_trust_request(db, workspace_slug="acme")
        assert wid == 3
        assert method == "slug"

    def test_slug_not_found(self):
        from app.api.routes.trust_requests import resolve_workspace_for_trust_request
        from fastapi import HTTPException

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            resolve_workspace_for_trust_request(db, workspace_slug="nope")
        assert exc_info.value.status_code == 404

    def test_default_fallback_dev(self):
        from app.api.routes.trust_requests import resolve_workspace_for_trust_request

        db = MagicMock()
        ws = MagicMock()
        ws.id = 1
        db.query.return_value.filter.return_value.first.return_value = ws

        wid, method = resolve_workspace_for_trust_request(db)
        assert wid == 1
        assert method == "default_dev"

    def test_no_workspace_at_all(self):
        from app.api.routes.trust_requests import resolve_workspace_for_trust_request
        from fastapi import HTTPException

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            resolve_workspace_for_trust_request(db)
        assert exc_info.value.status_code == 500

    def test_slug_takes_priority_over_explicit_id(self):
        from app.api.routes.trust_requests import resolve_workspace_for_trust_request

        db = MagicMock()
        ws = MagicMock()
        ws.id = 7
        db.query.return_value.filter.return_value.first.return_value = ws

        wid, method = resolve_workspace_for_trust_request(db, workspace_id=99, workspace_slug="other")
        assert wid == 7
        assert method == "slug"


class TestAttachmentDownload:
    """Test the attachment download endpoint."""

    def test_no_attachment_returns_404(self, _mock_db):
        from app.core.auth_deps import require_can_review

        mock_req = MagicMock()
        mock_req.workspace_id = 1
        mock_req.deleted_at = None
        mock_req.attachment_storage_key = None
        _mock_db.query.return_value.filter.return_value.first.return_value = mock_req

        app.dependency_overrides[require_can_review] = lambda: {"workspace_id": 1, "user_id": 1}

        r = client.get("/api/trust-requests/1/attachment")
        assert r.status_code == 404
        assert "no attachment" in r.json()["detail"].lower()

        app.dependency_overrides.pop(require_can_review, None)

    def test_missing_trust_request_returns_404(self, _mock_db):
        from app.core.auth_deps import require_can_review

        _mock_db.query.return_value.filter.return_value.first.return_value = None

        app.dependency_overrides[require_can_review] = lambda: {"workspace_id": 1, "user_id": 1}

        r = client.get("/api/trust-requests/999/attachment")
        assert r.status_code == 404

        app.dependency_overrides.pop(require_can_review, None)


class TestToDictFields:
    """Test that _to_dict includes new fields."""

    def test_to_dict_includes_new_fields(self):
        from app.api.routes.trust_requests import _to_dict

        mock_req = MagicMock()
        mock_req.id = 1
        mock_req.workspace_id = 2
        mock_req.assignee_id = None
        mock_req.requester_email = "x@y.com"
        mock_req.requester_name = "X"
        mock_req.subject = "S"
        mock_req.message = "M"
        mock_req.display_id = "TR-000001"
        mock_req.frameworks_json = '["Other"]'
        mock_req.subject_areas_json = '["Other"]'
        mock_req.status = "new"
        mock_req.attachment_filename = "report.pdf"
        mock_req.attachment_storage_key = "trust-requests/2/1/abc.pdf"
        mock_req.attachment_size = 12345
        mock_req.submitted_host = "trust.example.com"
        mock_req.submitted_path = "/trust/acme"
        mock_req.resolution_method = "slug"
        mock_req.created_at = None
        mock_req.deleted_at = None

        result = _to_dict(mock_req)

        assert result["attachment_filename"] == "report.pdf"
        assert result["attachment_size"] == 12345
        assert result["submitted_host"] == "trust.example.com"
        assert result["submitted_path"] == "/trust/acme"
        assert result["resolution_method"] == "slug"
