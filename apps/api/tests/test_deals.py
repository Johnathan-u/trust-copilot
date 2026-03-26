"""Tests for deal management and analytics (E1-01, E1-04, E1-05, E1-06, E1-07)."""

import pytest
from app.models.workspace import Workspace
from app.services import deal_service as ds
from app.services import revenue_risk_service as rrs
from app.services import deal_room_service as drs
from app.services import deal_deadline_service as dds
from app.services import deal_analytics_service as das


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


class TestDealService:
    def test_create_deal(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ds.create_deal(db_session, ws.id, "Test Corp", deal_value_arr=100000, stage="prospect")
        db_session.commit()
        assert result["company_name"] == "Test Corp"
        assert result["deal_value_arr"] == 100000

    def test_list_deals(self, db_session):
        ws = db_session.query(Workspace).first()
        ds.create_deal(db_session, ws.id, "Corp A", stage="prospect")
        ds.create_deal(db_session, ws.id, "Corp B", stage="evaluation")
        db_session.commit()
        deals = ds.list_deals(db_session, ws.id)
        assert len(deals) >= 2

    def test_filter_by_stage(self, db_session):
        ws = db_session.query(Workspace).first()
        ds.create_deal(db_session, ws.id, "Filter Corp", stage="negotiation")
        db_session.commit()
        deals = ds.list_deals(db_session, ws.id, stage="negotiation")
        assert all(d["stage"] == "negotiation" for d in deals)

    def test_update_deal(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ds.create_deal(db_session, ws.id, "Update Corp")
        db_session.commit()
        updated = ds.update_deal(db_session, created["id"], stage="closed_won")
        db_session.commit()
        assert updated["stage"] == "closed_won"

    def test_delete_deal(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ds.create_deal(db_session, ws.id, "Delete Corp")
        db_session.commit()
        assert ds.delete_deal(db_session, created["id"]) is True
        db_session.commit()
        assert ds.get_deal(db_session, created["id"]) is None

    def test_link_questionnaire(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ds.create_deal(db_session, ws.id, "Link Corp")
        db_session.commit()
        result = ds.link_questionnaire(db_session, created["id"], 42)
        db_session.commit()
        assert 42 in result["linked_questionnaire_ids"]


class TestRevenueRiskService:
    def test_score_deal(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ds.create_deal(db_session, ws.id, "Risk Corp", deal_value_arr=200000)
        db_session.commit()
        score = rrs.score_deal(db_session, created["id"])
        assert "risk_score" in score
        assert "revenue_at_risk" in score
        assert "breakdown" in score

    def test_rank_deals(self, db_session):
        ws = db_session.query(Workspace).first()
        ds.create_deal(db_session, ws.id, "Rank A", deal_value_arr=100000)
        ds.create_deal(db_session, ws.id, "Rank B", deal_value_arr=50000)
        db_session.commit()
        ranked = rrs.rank_deals_by_risk(db_session, ws.id)
        assert len(ranked) >= 2


class TestDealRoomService:
    def test_generate_room(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ds.create_deal(db_session, ws.id, "Room Corp")
        db_session.commit()
        room = drs.generate_deal_room(db_session, created["id"])
        assert "access_token" in room
        assert "questionnaires" in room
        assert "trust_center_articles" in room


class TestDealDeadlineService:
    def test_upcoming_deadlines(self, db_session):
        ws = db_session.query(Workspace).first()
        from datetime import datetime, timedelta, timezone
        future = datetime.now(timezone.utc) + timedelta(days=7)
        ds.create_deal(db_session, ws.id, "Deadline Corp", close_date=future)
        db_session.commit()
        upcoming = dds.get_upcoming_deadlines(db_session, ws.id, within_days=14)
        assert len(upcoming) >= 1

    def test_overdue_deals(self, db_session):
        ws = db_session.query(Workspace).first()
        from datetime import datetime, timedelta, timezone
        past = datetime.now(timezone.utc) - timedelta(days=5)
        ds.create_deal(db_session, ws.id, "Overdue Corp", close_date=past, stage="evaluation")
        db_session.commit()
        overdue = dds.get_overdue_deals(db_session, ws.id)
        assert len(overdue) >= 1


class TestDealAnalyticsService:
    def test_analytics(self, db_session):
        ws = db_session.query(Workspace).first()
        ds.create_deal(db_session, ws.id, "Analytics Corp", stage="closed_won", deal_value_arr=80000)
        db_session.commit()
        result = das.get_analytics(db_session, ws.id)
        assert result["total_deals"] >= 1
        assert "by_stage" in result

    def test_revenue_unblocked(self, db_session):
        ws = db_session.query(Workspace).first()
        result = das.get_revenue_unblocked(db_session, ws.id)
        assert "total_revenue_unblocked" in result


class TestDealAPI:
    def test_create_deal(self, admin_client):
        r = admin_client.post("/api/deals", json={
            "company_name": "API Corp", "deal_value_arr": 120000, "stage": "prospect",
        })
        assert r.status_code == 200
        assert r.json()["company_name"] == "API Corp"

    def test_list_deals(self, admin_client):
        r = admin_client.get("/api/deals")
        assert r.status_code == 200
        assert "deals" in r.json()

    def test_analytics(self, admin_client):
        r = admin_client.get("/api/deals/analytics")
        assert r.status_code == 200
        assert "total_deals" in r.json()

    def test_risk_ranking(self, admin_client):
        r = admin_client.get("/api/deals/risk-ranking")
        assert r.status_code == 200

    def test_upcoming_deadlines(self, admin_client):
        r = admin_client.get("/api/deals/upcoming-deadlines")
        assert r.status_code == 200

    def test_editor_can_read(self, editor_client):
        r = editor_client.get("/api/deals")
        assert r.status_code == 200

    def test_editor_cannot_create(self, editor_client):
        r = editor_client.post("/api/deals", json={"company_name": "No"})
        assert r.status_code == 403
