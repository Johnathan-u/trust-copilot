"""Tests for admin-configurable workspace dashboard cards.

Covers: CRUD, reorder, workspace isolation, permission enforcement,
route validation, visibility filtering, default fallback.
"""

import pytest
from fastapi.testclient import TestClient


def _login_admin_ws1(client: TestClient):
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1
        ).first()
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200


def _make_editor(client: TestClient):
    """Change demo user to editor and re-login so session token reflects the new role."""
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1
        ).first()
        mem.role = "editor"
        db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200


def _cleanup_cards():
    from app.core.database import SessionLocal
    from app.models.dashboard_card import DashboardCard
    db = SessionLocal()
    try:
        db.query(DashboardCard).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean():
    _cleanup_cards()
    yield
    _cleanup_cards()


class TestDefaultFallback:
    def test_returns_defaults_when_no_custom_cards(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.get("/api/dashboard/cards")
        assert r.status_code == 200
        data = r.json()
        assert data["has_custom"] is False
        assert len(data["cards"]) == 4
        assert all(c.get("is_builtin") is True for c in data["cards"])


class TestAdminCRUD:
    def test_create_card(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "Documents",
            "description": "Upload docs",
            "icon": "document",
            "target_route": "/dashboard/documents",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Documents"
        assert data["id"] is not None
        assert data["workspace_id"] == 1
        assert data["sort_order"] == 0

    def test_create_second_card_increments_order(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "First", "icon": "document", "target_route": "/dashboard/documents",
        })
        r2 = client.post("/api/dashboard/cards", json={
            "title": "Second", "icon": "export", "target_route": "/dashboard/exports",
        })
        assert r2.json()["sort_order"] == 1

    def test_update_card(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "Old Title", "icon": "document", "target_route": "/dashboard/documents",
        })
        card_id = r.json()["id"]
        r2 = client.patch(f"/api/dashboard/cards/{card_id}", json={"title": "New Title"})
        assert r2.status_code == 200
        assert r2.json()["title"] == "New Title"

    def test_delete_card(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "ToDelete", "icon": "document", "target_route": "/dashboard/documents",
        })
        card_id = r.json()["id"]
        r2 = client.delete(f"/api/dashboard/cards/{card_id}")
        assert r2.status_code == 200
        r3 = client.get("/api/dashboard/cards")
        data = r3.json()
        assert data["has_custom"] is False
        assert len(data["cards"]) == 4
        assert not any(c.get("title") == "ToDelete" for c in data["cards"])

    def test_list_returns_defaults_plus_custom(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "Custom Card", "icon": "star", "target_route": "/dashboard/exports",
        })
        r = client.get("/api/dashboard/cards")
        data = r.json()
        assert data["has_custom"] is True
        builtins = [c for c in data["cards"] if c.get("is_builtin")]
        customs = [c for c in data["cards"] if not c.get("is_builtin")]
        assert len(builtins) == 4
        assert len(customs) == 1
        assert customs[0]["title"] == "Custom Card"


class TestReorder:
    def test_reorder_custom_cards(self, client: TestClient):
        _login_admin_ws1(client)
        r1 = client.post("/api/dashboard/cards", json={
            "title": "A", "icon": "document", "target_route": "/dashboard/documents",
        })
        r2 = client.post("/api/dashboard/cards", json={
            "title": "B", "icon": "export", "target_route": "/dashboard/exports",
        })
        id_a, id_b = r1.json()["id"], r2.json()["id"]
        r = client.post("/api/dashboard/cards/reorder", json={"card_ids": [id_b, id_a]})
        assert r.status_code == 200
        all_cards = client.get("/api/dashboard/cards").json()["cards"]
        customs = [c for c in all_cards if not c.get("is_builtin")]
        assert customs[0]["title"] == "B"
        assert customs[1]["title"] == "A"
        builtins = [c for c in all_cards if c.get("is_builtin")]
        assert len(builtins) == 4


class TestNonAdminBlocked:
    def test_editor_cannot_create(self, client: TestClient):
        _login_admin_ws1(client)
        _make_editor(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "Nope", "icon": "document", "target_route": "/dashboard/documents",
        })
        assert r.status_code == 403

    def test_editor_cannot_delete(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "X", "icon": "document", "target_route": "/dashboard/documents",
        })
        card_id = r.json()["id"]
        _make_editor(client)
        r2 = client.delete(f"/api/dashboard/cards/{card_id}")
        assert r2.status_code == 403

    def test_editor_cannot_reorder(self, client: TestClient):
        _login_admin_ws1(client)
        _make_editor(client)
        r = client.post("/api/dashboard/cards/reorder", json={"card_ids": [1]})
        assert r.status_code == 403

    def test_editor_can_list_cards(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "Visible", "icon": "star", "target_route": "/dashboard/documents",
            "visibility_scope": "all",
        })
        _make_editor(client)
        r = client.get("/api/dashboard/cards")
        assert r.status_code == 200
        assert any(c["title"] == "Visible" for c in r.json()["cards"])


class TestWorkspaceIsolation:
    def test_cards_scoped_to_workspace(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "WS1 Card", "icon": "document", "target_route": "/dashboard/documents",
        })

        # Switch to workspace 2 (demo user is member of both)
        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "demo@trust.local").first()
            mem2 = db.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 2
            ).first()
            mem2.role = "admin"
            db.commit()
        finally:
            db.close()

        client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
        r = client.get("/api/dashboard/cards")
        customs = [c for c in r.json()["cards"] if not c.get("is_builtin")]
        assert not any(c.get("title") == "WS1 Card" for c in customs)

    def test_cannot_update_other_workspace_card(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "WS1 Only", "icon": "document", "target_route": "/dashboard/documents",
        })
        card_id = r.json()["id"]

        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "demo@trust.local").first()
            mem2 = db.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 2
            ).first()
            mem2.role = "admin"
            db.commit()
        finally:
            db.close()

        client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
        r2 = client.patch(f"/api/dashboard/cards/{card_id}", json={"title": "Hijacked"})
        assert r2.status_code == 404

    def test_cannot_delete_other_workspace_card(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "WS1 Only", "icon": "document", "target_route": "/dashboard/documents",
        })
        card_id = r.json()["id"]

        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "demo@trust.local").first()
            mem2 = db.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 2
            ).first()
            mem2.role = "admin"
            db.commit()
        finally:
            db.close()

        client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
        r2 = client.delete(f"/api/dashboard/cards/{card_id}")
        assert r2.status_code == 404


class TestValidation:
    def test_invalid_route_rejected(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "Bad", "icon": "document", "target_route": "/evil/path",
        })
        assert r.status_code == 422

    def test_invalid_icon_rejected(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "Bad", "icon": "not_an_icon", "target_route": "/dashboard/documents",
        })
        assert r.status_code == 422

    def test_invalid_visibility_rejected(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "Bad", "icon": "document", "target_route": "/dashboard/documents",
            "visibility_scope": "hacker",
        })
        assert r.status_code == 422


class TestVisibilityFiltering:
    def test_admin_only_cards_hidden_from_editor(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "Public Card", "icon": "document", "target_route": "/dashboard/documents",
            "visibility_scope": "all",
        })
        client.post("/api/dashboard/cards", json={
            "title": "Admin Secret", "icon": "security", "target_route": "/dashboard/security",
            "visibility_scope": "admin",
        })
        _make_editor(client)
        r = client.get("/api/dashboard/cards")
        cards = r.json()["cards"]
        titles = [c["title"] for c in cards]
        assert "Public Card" in titles
        assert "Admin Secret" not in titles
        builtins = [c for c in cards if c.get("is_builtin")]
        assert len(builtins) == 4

    def test_disabled_cards_hidden_from_editor(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "Disabled Card", "icon": "document", "target_route": "/dashboard/documents",
            "is_enabled": False,
        })
        _make_editor(client)
        r2 = client.get("/api/dashboard/cards")
        cards = r2.json()["cards"]
        assert not any(c["title"] == "Disabled Card" for c in cards)
        builtins = [c for c in cards if c.get("is_builtin")]
        assert len(builtins) == 4


class TestAllowedRoutes:
    def test_get_allowed_routes_admin_only(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.get("/api/dashboard/cards/allowed-routes")
        assert r.status_code == 200
        data = r.json()
        assert "routes" in data
        assert "icons" in data
        assert len(data["routes"]) > 5

    def test_editor_cannot_get_allowed_routes(self, client: TestClient):
        _login_admin_ws1(client)
        _make_editor(client)
        r = client.get("/api/dashboard/cards/allowed-routes")
        assert r.status_code == 403


class TestDefaultsPersist:
    def test_defaults_remain_after_adding_custom(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "My Custom", "icon": "star", "target_route": "/dashboard/compliance-gaps",
        })
        r = client.get("/api/dashboard/cards")
        data = r.json()
        builtins = [c for c in data["cards"] if c.get("is_builtin")]
        customs = [c for c in data["cards"] if not c.get("is_builtin")]
        assert len(builtins) == 4
        assert len(customs) == 1
        builtin_titles = {c["title"] for c in builtins}
        assert builtin_titles == {"Documents", "Questionnaires", "Exports", "Trust Center"}

    def test_defaults_remain_after_deleting_all_custom(self, client: TestClient):
        _login_admin_ws1(client)
        r1 = client.post("/api/dashboard/cards", json={
            "title": "Temp", "icon": "document", "target_route": "/dashboard/documents",
        })
        card_id = r1.json()["id"]
        client.delete(f"/api/dashboard/cards/{card_id}")
        r = client.get("/api/dashboard/cards")
        data = r.json()
        assert data["has_custom"] is False
        assert len(data["cards"]) == 4
        assert all(c.get("is_builtin") for c in data["cards"])

    def test_builtins_appear_before_custom(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "Custom First?", "icon": "star", "target_route": "/dashboard/compliance-gaps",
        })
        r = client.get("/api/dashboard/cards")
        cards = r.json()["cards"]
        first_custom_idx = next(i for i, c in enumerate(cards) if not c.get("is_builtin"))
        last_builtin_idx = max(i for i, c in enumerate(cards) if c.get("is_builtin"))
        assert last_builtin_idx < first_custom_idx


class TestAuditEvents:
    def test_create_produces_audit_event(self, client: TestClient):
        _login_admin_ws1(client)
        client.post("/api/dashboard/cards", json={
            "title": "Audited", "icon": "document", "target_route": "/dashboard/documents",
        })
        from app.core.database import SessionLocal
        from app.models import AuditEvent
        db = SessionLocal()
        try:
            ev = db.query(AuditEvent).filter(
                AuditEvent.action == "dashboard.card_created",
                AuditEvent.workspace_id == 1,
            ).order_by(AuditEvent.id.desc()).first()
            assert ev is not None
        finally:
            db.close()

    def test_delete_produces_audit_event(self, client: TestClient):
        _login_admin_ws1(client)
        r = client.post("/api/dashboard/cards", json={
            "title": "ToAudit", "icon": "document", "target_route": "/dashboard/documents",
        })
        card_id = r.json()["id"]
        client.delete(f"/api/dashboard/cards/{card_id}")
        from app.core.database import SessionLocal
        from app.models import AuditEvent
        db = SessionLocal()
        try:
            ev = db.query(AuditEvent).filter(
                AuditEvent.action == "dashboard.card_deleted",
                AuditEvent.workspace_id == 1,
            ).order_by(AuditEvent.id.desc()).first()
            assert ev is not None
        finally:
            db.close()
