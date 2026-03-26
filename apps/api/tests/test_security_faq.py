"""Tests for the security and data-handling FAQ system (P0-12)."""

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


class TestSecurityFAQService:
    def test_seed_defaults(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.security_faq_service import seed_defaults, list_faqs, DEFAULT_FAQ
        db = SessionLocal()
        try:
            created = seed_defaults(db, 1)
            db.commit()
            if created > 0:
                assert created == len(DEFAULT_FAQ)
            faqs = list_faqs(db, 1)
            assert len(faqs) >= len(DEFAULT_FAQ)
        finally:
            db.close()

    def test_list_by_category(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.security_faq_service import seed_defaults, list_faqs
        db = SessionLocal()
        try:
            seed_defaults(db, 1)
            db.commit()
            storage = list_faqs(db, 1, category="data_storage")
            assert all(f["category"] == "data_storage" for f in storage)
            assert len(storage) >= 2
        finally:
            db.close()

    def test_search(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.security_faq_service import seed_defaults, list_faqs
        db = SessionLocal()
        try:
            seed_defaults(db, 1)
            db.commit()
            mfa = list_faqs(db, 1, search="MFA")
            assert len(mfa) >= 1
        finally:
            db.close()

    def test_filter_by_framework(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.security_faq_service import seed_defaults, list_faqs
        db = SessionLocal()
        try:
            seed_defaults(db, 1)
            db.commit()
            hipaa = list_faqs(db, 1, framework="HIPAA")
            assert len(hipaa) >= 3
        finally:
            db.close()

    def test_create_custom(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.security_faq_service import create_faq
        db = SessionLocal()
        try:
            item = create_faq(db, 1, "custom", "Custom Q?", "Custom A.", framework_tags="SOC2")
            db.commit()
            assert item["is_default"] is False
            assert item["category"] == "custom"
        finally:
            db.close()

    def test_get_categories(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.security_faq_service import seed_defaults, get_categories
        db = SessionLocal()
        try:
            seed_defaults(db, 1)
            db.commit()
            cats = get_categories(db, 1)
            assert "data_storage" in cats
            assert "access_control" in cats
        finally:
            db.close()


class TestSecurityFAQAPI:
    def test_seed(self, admin_client):
        r = admin_client.post("/api/security-faq/seed")
        assert r.status_code == 200
        assert "created" in r.json()

    def test_list(self, admin_client):
        admin_client.post("/api/security-faq/seed")
        r = admin_client.get("/api/security-faq")
        assert r.status_code == 200
        assert len(r.json()["faqs"]) >= 15

    def test_list_by_category(self, admin_client):
        admin_client.post("/api/security-faq/seed")
        r = admin_client.get("/api/security-faq?category=data_storage")
        assert r.status_code == 200
        for faq in r.json()["faqs"]:
            assert faq["category"] == "data_storage"

    def test_search(self, admin_client):
        admin_client.post("/api/security-faq/seed")
        r = admin_client.get("/api/security-faq?search=encryption")
        assert r.status_code == 200
        assert len(r.json()["faqs"]) >= 1

    def test_filter_framework(self, admin_client):
        admin_client.post("/api/security-faq/seed")
        r = admin_client.get("/api/security-faq?framework=GDPR")
        assert r.status_code == 200
        assert len(r.json()["faqs"]) >= 2

    def test_categories(self, admin_client):
        admin_client.post("/api/security-faq/seed")
        r = admin_client.get("/api/security-faq/categories")
        assert r.status_code == 200
        assert "data_storage" in r.json()["categories"]

    def test_create_custom(self, admin_client):
        r = admin_client.post("/api/security-faq", json={
            "category": "custom_test",
            "question": "API test question?",
            "answer": "API test answer.",
            "framework_tags": "SOC2,ISO27001",
        })
        assert r.status_code == 200
        assert r.json()["category"] == "custom_test"

    def test_update(self, admin_client):
        r1 = admin_client.post("/api/security-faq", json={
            "category": "update_test",
            "question": "Original?",
            "answer": "Original.",
        })
        faq_id = r1.json()["id"]
        r2 = admin_client.patch(f"/api/security-faq/{faq_id}", json={"answer": "Updated answer."})
        assert r2.status_code == 200
        assert r2.json()["answer"] == "Updated answer."

    def test_delete(self, admin_client):
        r1 = admin_client.post("/api/security-faq", json={
            "category": "del_test",
            "question": "Delete me?",
            "answer": "Sure.",
        })
        faq_id = r1.json()["id"]
        r2 = admin_client.delete(f"/api/security-faq/{faq_id}")
        assert r2.status_code == 200
        r3 = admin_client.get(f"/api/security-faq/{faq_id}")
        assert r3.status_code == 404

    def test_editor_can_read(self, editor_client):
        r = editor_client.get("/api/security-faq")
        assert r.status_code == 200

    def test_editor_cannot_create(self, editor_client):
        r = editor_client.post("/api/security-faq", json={
            "category": "test",
            "question": "Q?",
            "answer": "A.",
        })
        assert r.status_code == 403

    def test_empty_question_rejected(self, admin_client):
        r = admin_client.post("/api/security-faq", json={
            "category": "test",
            "question": "  ",
            "answer": "A.",
        })
        assert r.status_code == 400
