"""Tests for the operator queue system (P0-11)."""

import pytest


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


class TestOperatorQueueService:
    """Direct service-layer tests."""

    def test_create_and_get(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.operator_queue_service import create_item, get_item
        db = SessionLocal()
        try:
            item = create_item(db, 1, "Test questionnaire from Acme", customer_name="Acme Corp", priority="high")
            db.commit()
            assert item["title"] == "Test questionnaire from Acme"
            assert item["status"] == "received"
            assert item["priority"] == "high"
            assert item["customer_name"] == "Acme Corp"

            fetched = get_item(db, item["id"])
            assert fetched is not None
            assert fetched["id"] == item["id"]
        finally:
            db.close()

    def test_update_status(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.operator_queue_service import create_item, update_item
        db = SessionLocal()
        try:
            item = create_item(db, 1, "Update test", priority="normal")
            db.commit()
            updated = update_item(db, item["id"], status="in_progress", assignee="operator@test.local")
            db.commit()
            assert updated["status"] == "in_progress"
            assert updated["assignee"] == "operator@test.local"
        finally:
            db.close()

    def test_invalid_status_ignored(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.operator_queue_service import create_item, update_item
        db = SessionLocal()
        try:
            item = create_item(db, 1, "Bad status test")
            db.commit()
            updated = update_item(db, item["id"], status="invalid_status")
            db.commit()
            assert updated["status"] == "received"
        finally:
            db.close()

    def test_list_with_filters(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.operator_queue_service import create_item, list_items, update_item
        db = SessionLocal()
        try:
            item1 = create_item(db, 1, "Filter A", priority="critical")
            item2 = create_item(db, 1, "Filter B", priority="low")
            db.commit()
            update_item(db, item1["id"], status="in_progress")
            db.commit()

            critical = list_items(db, 1, priority="critical")
            assert any(i["title"] == "Filter A" for i in critical)

            in_progress = list_items(db, 1, status="in_progress")
            assert any(i["title"] == "Filter A" for i in in_progress)
        finally:
            db.close()

    def test_delete(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.operator_queue_service import create_item, delete_item, get_item
        db = SessionLocal()
        try:
            item = create_item(db, 1, "Delete me")
            db.commit()
            assert delete_item(db, item["id"])
            db.commit()
            assert get_item(db, item["id"]) is None
        finally:
            db.close()

    def test_dashboard_stats(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.operator_queue_service import dashboard_stats
        db = SessionLocal()
        try:
            stats = dashboard_stats(db, 1)
            assert "total" in stats
            assert "by_status" in stats
            assert "by_priority" in stats
            assert "overdue" in stats
        finally:
            db.close()


class TestOperatorQueueAPI:
    """HTTP-level tests."""

    def test_create_item(self, admin_client):
        r = admin_client.post("/api/operator-queue", json={
            "title": "SOC 2 questionnaire from BigCo",
            "customer_name": "BigCo Inc",
            "priority": "high",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "SOC 2 questionnaire from BigCo"
        assert data["status"] == "received"
        assert data["priority"] == "high"

    def test_list_items(self, admin_client):
        r = admin_client.get("/api/operator-queue")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_get_item(self, admin_client):
        r1 = admin_client.post("/api/operator-queue", json={"title": "Get test"})
        assert r1.status_code == 200
        item_id = r1.json()["id"]
        r2 = admin_client.get(f"/api/operator-queue/{item_id}")
        assert r2.status_code == 200
        assert r2.json()["title"] == "Get test"

    def test_update_item(self, admin_client):
        r1 = admin_client.post("/api/operator-queue", json={"title": "Update test"})
        item_id = r1.json()["id"]
        r2 = admin_client.patch(f"/api/operator-queue/{item_id}", json={
            "status": "in_progress",
            "assignee": "me@test.local",
        })
        assert r2.status_code == 200
        assert r2.json()["status"] == "in_progress"
        assert r2.json()["assignee"] == "me@test.local"

    def test_delete_item(self, admin_client):
        r1 = admin_client.post("/api/operator-queue", json={"title": "Delete test"})
        item_id = r1.json()["id"]
        r2 = admin_client.delete(f"/api/operator-queue/{item_id}")
        assert r2.status_code == 200
        r3 = admin_client.get(f"/api/operator-queue/{item_id}")
        assert r3.status_code == 404

    def test_dashboard(self, admin_client):
        r = admin_client.get("/api/operator-queue/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "overdue" in data

    def test_editor_forbidden(self, editor_client):
        r = editor_client.get("/api/operator-queue")
        assert r.status_code == 403

    def test_editor_create_forbidden(self, editor_client):
        r = editor_client.post("/api/operator-queue", json={"title": "Should fail"})
        assert r.status_code == 403

    def test_empty_title_rejected(self, admin_client):
        r = admin_client.post("/api/operator-queue", json={"title": "  "})
        assert r.status_code == 400

    def test_filter_by_status(self, admin_client):
        admin_client.post("/api/operator-queue", json={"title": "Filter status test"})
        r = admin_client.get("/api/operator-queue?status=received")
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["status"] == "received"

    def test_not_found(self, admin_client):
        r = admin_client.get("/api/operator-queue/999999")
        assert r.status_code == 404
