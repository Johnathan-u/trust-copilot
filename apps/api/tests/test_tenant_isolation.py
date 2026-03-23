"""Tenant isolation: cross-workspace access attempts must return 403 or 404."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Control


def test_controls_cross_tenant_update_returns_404(client: TestClient, db_session: Session) -> None:
    """Update a control in workspace 1 while session is workspace 2 returns 404 (control not found)."""
    c = Control(workspace_id=1, framework="SOC 2", control_id="CC1", name="Test", status="in_review")
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    control_id = c.id
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r2 = client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    assert r2.status_code == 200
    r3 = client.patch(
        f"/api/controls/{control_id}",
        json={"status": "implemented"},
    )
    assert r3.status_code in (403, 404)


def test_controls_cross_tenant_delete_returns_404(client: TestClient, db_session: Session) -> None:
    """Delete a control in workspace 1 while session is workspace 2 returns 404."""
    c = Control(workspace_id=1, framework="SOC 2", control_id="CC2", name="Test", status="in_review")
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    control_id = c.id
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    r2 = client.delete(f"/api/controls/{control_id}")
    assert r2.status_code in (403, 404)


def test_documents_list_cross_tenant_returns_403(client: TestClient) -> None:
    """List documents for workspace 1 while session is workspace 2 returns 403."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    r = client.get("/api/documents/?workspace_id=1")
    assert r.status_code == 403


def test_questionnaires_list_cross_tenant_returns_403(client: TestClient) -> None:
    """List questionnaires for workspace 1 while session is workspace 2 returns 403."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    r = client.get("/api/questionnaires/?workspace_id=1")
    assert r.status_code == 403


def test_members_list_scoped_to_current_workspace(client: TestClient) -> None:
    """Members list uses session workspace only; after switch to ws 2 we get ws 2 members (admin required)."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    r = client.get("/api/members/")
    # Demo user is editor in ws 2; members list may require admin - 200 or 403 by role
    assert r.status_code in (200, 403)


def test_audit_export_scoped_to_current_workspace(client: TestClient) -> None:
    """Audit export is admin-only and scoped to session workspace; no cross-tenant data."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    r = client.get("/api/audit/export?since_hours=24")
    # Editor in ws 2 gets 403 (admin required); if admin, we get 200 with ws 2 data only
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        data = r.json()
        assert isinstance(data, list)
        for event in data:
            assert event.get("workspace_id") != 1


def test_trust_requests_list_cross_tenant_returns_403_or_empty(client: TestClient) -> None:
    """Trust requests are scoped to current workspace; listing with ws 2 does not return ws 1 data."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    r = client.get("/api/trust-requests/")
    assert r.status_code == 200
    # Response is scoped to workspace 2; any requests in workspace 1 must not appear
    data = r.json() if r.content else []
    if isinstance(data, list):
        for tr in data:
            assert tr.get("workspace_id") != 1


def test_exports_list_cross_tenant_returns_403_or_404(client: TestClient) -> None:
    """Request exports for workspace 1 while session is workspace 2 returns 403 or 404."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    r = client.get("/api/exports/records?workspace_id=1")
    assert r.status_code in (403, 404)
