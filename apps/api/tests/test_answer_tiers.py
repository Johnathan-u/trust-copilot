"""Tests for answer tiers (P1-69)."""

import pytest
from app.services import answer_tiers_service as at


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestAnswerTiersService:
    def test_classify_answers(self, db_session):
        result = at.classify_answers(db_session)
        assert "total" in result
        assert "by_tier" in result
        for tier in at.VALID_TIERS:
            assert tier in result["by_tier"]

    def test_invalid_tier_rejected(self, db_session):
        result = at.set_answer_tier(db_session, 1, "invalid_tier")
        if result:
            assert "error" in result


class TestAnswerTiersAPI:
    def test_classify(self, admin_client):
        r = admin_client.get("/api/answer-tiers/classify")
        assert r.status_code == 200
        assert "by_tier" in r.json()
