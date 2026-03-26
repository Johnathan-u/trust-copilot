"""Tests for the credit ledger system (P0-10)."""

import pytest


@pytest.fixture
def admin_client(client):
    """Login as admin and return the client."""
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return client


@pytest.fixture
def editor_client(client):
    """Login as editor (non-admin) and return the client."""
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert r.status_code == 200, f"Editor login failed: {r.text}"
    return client


# ---------------------------------------------------------------------------
# Service-layer unit tests
# ---------------------------------------------------------------------------

class TestCreditServiceUnit:
    """Direct service-layer tests (no HTTP)."""

    def test_credits_required_calculation(self):
        from app.services.credit_service import credits_required
        assert credits_required(1) == 1
        assert credits_required(100) == 1
        assert credits_required(101) == 2
        assert credits_required(200) == 2
        assert credits_required(201) == 3
        assert credits_required(0) == 1
        assert credits_required(-5) == 1

    def test_get_or_create_ledger(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.credit_service import get_or_create_ledger
        db = SessionLocal()
        try:
            ledger = get_or_create_ledger(db, 1)
            assert ledger is not None
            assert ledger.workspace_id == 1
            assert ledger.balance >= 0
            assert ledger.monthly_allocation > 0
            db.commit()
        finally:
            db.close()

    def test_consume_and_balance(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.credit_service import (
            add_credits, consume, get_balance, get_or_create_ledger,
        )
        db = SessionLocal()
        try:
            ledger = get_or_create_ledger(db, 1)
            add_credits(db, 1, 50, description="test top-up")
            db.commit()

            before = get_balance(db, 1)
            result = consume(db, 1, 150, questionnaire_id=None)
            db.commit()
            assert result["consumed"] == 2
            assert result["balance"] == before["balance"] - 2
        finally:
            db.close()

    def test_consume_insufficient_raises(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.credit_service import get_or_create_ledger, consume

        db = SessionLocal()
        try:
            ledger = get_or_create_ledger(db, 1)
            ledger.balance = 0
            db.flush()
            db.commit()

            with pytest.raises(ValueError, match="Insufficient credits"):
                consume(db, 1, 100)
        finally:
            db.close()

    def test_reset_cycle(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.credit_service import get_or_create_ledger, reset_cycle

        db = SessionLocal()
        try:
            ledger = get_or_create_ledger(db, 1)
            ledger.balance = 3
            db.commit()

            result = reset_cycle(db, 1)
            db.commit()
            assert result["balance"] == ledger.monthly_allocation
        finally:
            db.close()

    def test_transaction_history(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.credit_service import get_transactions, add_credits

        db = SessionLocal()
        try:
            add_credits(db, 1, 5, description="history test")
            db.commit()
            txns = get_transactions(db, 1, limit=5)
            assert len(txns) > 0
            assert txns[0]["kind"] in ("purchase", "allocation", "consumption", "reset", "adjustment")
        finally:
            db.close()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestCreditAPI:
    """HTTP-level tests for credit endpoints."""

    def test_get_balance(self, admin_client):
        r = admin_client.get("/api/credits")
        assert r.status_code == 200
        data = r.json()
        assert "balance" in data
        assert "monthly_allocation" in data

    def test_get_balance_as_editor(self, editor_client):
        r = editor_client.get("/api/credits")
        assert r.status_code == 200
        data = r.json()
        assert "balance" in data

    def test_add_credits_admin(self, admin_client):
        before = admin_client.get("/api/credits").json()["balance"]
        r = admin_client.post("/api/credits/add", json={"amount": 10, "description": "test add"})
        assert r.status_code == 200
        assert r.json()["balance"] == before + 10

    def test_add_credits_editor_forbidden(self, editor_client):
        r = editor_client.post("/api/credits/add", json={"amount": 5})
        assert r.status_code == 403

    def test_add_credits_zero_rejected(self, admin_client):
        r = admin_client.post("/api/credits/add", json={"amount": 0})
        assert r.status_code == 400

    def test_update_allocation(self, admin_client):
        r = admin_client.patch("/api/credits/allocation", json={"monthly_allocation": 25})
        assert r.status_code == 200
        assert r.json()["monthly_allocation"] == 25
        admin_client.patch("/api/credits/allocation", json={"monthly_allocation": 15})

    def test_update_allocation_editor_forbidden(self, editor_client):
        r = editor_client.patch("/api/credits/allocation", json={"monthly_allocation": 25})
        assert r.status_code == 403

    def test_reset_cycle(self, admin_client):
        r = admin_client.post("/api/credits/reset-cycle")
        assert r.status_code == 200
        assert "balance" in r.json()

    def test_transactions(self, admin_client):
        r = admin_client.get("/api/credits/transactions")
        assert r.status_code == 200
        data = r.json()
        assert "transactions" in data
        assert isinstance(data["transactions"], list)

    def test_check_credits(self, admin_client):
        r = admin_client.get("/api/credits/check?question_count=50")
        assert r.status_code == 200
        data = r.json()
        assert "sufficient" in data
        assert "balance" in data
        assert "required" in data
        assert data["required"] == 1

    def test_check_credits_large(self, admin_client):
        r = admin_client.get("/api/credits/check?question_count=500")
        assert r.status_code == 200
        assert r.json()["required"] == 5

    def test_unauthenticated_rejected(self, client):
        r = client.get("/api/credits")
        assert r.status_code == 401
