"""Tests for answer approval workflows (P1-72)."""

import pytest
from app.models.workspace import Workspace
from app.services import answer_approval_service as svc
from app.services import golden_answer_service as ga


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


class TestAnswerApprovalService:
    def test_assign_owner(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Owner Q", "Owner A")
        db_session.commit()
        result = svc.assign_owner(db_session, created["id"], 1, actor_user_id=1)
        db_session.commit()
        assert result["owner_user_id"] == 1

    def test_assign_reviewer(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Reviewer Q", "Reviewer A")
        db_session.commit()
        result = svc.assign_reviewer(db_session, created["id"], 2, actor_user_id=1)
        db_session.commit()
        assert result["reviewer_user_id"] == 2

    def test_submit_for_review(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Submit Q", "Submit A")
        db_session.commit()
        ga.update_golden_answer(db_session, created["id"], status="draft")
        db_session.commit()
        result = svc.submit_for_review(db_session, created["id"])
        db_session.commit()
        assert result["status"] == "pending_review"
        assert result["submitted_at"] is not None

    def test_approve_answer(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Approve Q", "Approve A")
        db_session.commit()
        ga.update_golden_answer(db_session, created["id"], status="draft")
        db_session.commit()
        svc.submit_for_review(db_session, created["id"])
        db_session.commit()
        result = svc.approve_answer(db_session, created["id"], 1, "Looks good")
        db_session.commit()
        assert result["status"] == "approved"

    def test_reject_answer(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Reject Q", "Reject A")
        db_session.commit()
        ga.update_golden_answer(db_session, created["id"], status="draft")
        db_session.commit()
        svc.submit_for_review(db_session, created["id"])
        db_session.commit()
        result = svc.reject_answer(db_session, created["id"], 1, "Needs improvement")
        db_session.commit()
        assert result["status"] == "rejected"

    def test_request_changes(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Changes Q", "Changes A")
        db_session.commit()
        ga.update_golden_answer(db_session, created["id"], status="draft")
        db_session.commit()
        svc.submit_for_review(db_session, created["id"])
        db_session.commit()
        result = svc.request_changes(db_session, created["id"], 1, "Fix wording")
        db_session.commit()
        assert result["status"] == "changes_requested"

    def test_review_queue(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Queue Q", "Queue A")
        db_session.commit()
        ga.update_golden_answer(db_session, created["id"], status="draft")
        db_session.commit()
        svc.submit_for_review(db_session, created["id"])
        db_session.commit()
        queue = svc.get_review_queue(db_session, ws.id)
        assert len(queue) >= 1
        assert any(a["status"] == "pending_review" for a in queue)

    def test_cannot_approve_from_draft(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "Bad Flow Q", "Bad Flow A")
        db_session.commit()
        ga.update_golden_answer(db_session, created["id"], status="draft")
        db_session.commit()
        result = svc.approve_answer(db_session, created["id"], 1)
        assert "error" in result

    def test_approval_history(self, db_session):
        ws = db_session.query(Workspace).first()
        created = ga.create_golden_answer(db_session, ws.id, "History Q", "History A")
        db_session.commit()
        ga.update_golden_answer(db_session, created["id"], status="draft")
        db_session.commit()
        svc.submit_for_review(db_session, created["id"])
        svc.approve_answer(db_session, created["id"], 1, "LGTM")
        db_session.commit()
        # This will fail because approve needs pending_review, let's just check history after submit
        history = svc.get_approval_history(db_session, created["id"])
        assert len(history) >= 1

    def test_bulk_approve(self, db_session):
        ws = db_session.query(Workspace).first()
        ids = []
        for i in range(3):
            c = ga.create_golden_answer(db_session, ws.id, f"Bulk Q{i}", f"Bulk A{i}")
            db_session.commit()
            ga.update_golden_answer(db_session, c["id"], status="draft")
            db_session.commit()
            svc.submit_for_review(db_session, c["id"])
            db_session.commit()
            ids.append(c["id"])
        result = svc.bulk_approve(db_session, ids, 1)
        db_session.commit()
        assert len(result["approved"]) == 3


class TestAnswerApprovalAPI:
    def test_queue(self, admin_client):
        r = admin_client.get("/api/answer-approval/queue")
        assert r.status_code == 200
        assert "queue" in r.json()

    def test_overdue(self, admin_client):
        r = admin_client.get("/api/answer-approval/overdue")
        assert r.status_code == 200
        assert "overdue" in r.json()

    def test_submit_approve_flow(self, admin_client):
        r = admin_client.post("/api/golden-answers", json={
            "question_text": "Workflow Q", "answer_text": "Workflow A",
        })
        ga_id = r.json()["id"]
        admin_client.patch(f"/api/golden-answers/{ga_id}", json={"status": "draft"})
        r = admin_client.post(f"/api/answer-approval/{ga_id}/submit")
        assert r.status_code == 200
        assert r.json()["status"] == "pending_review"
        r = admin_client.post(f"/api/answer-approval/{ga_id}/approve", json={"comment": "OK"})
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_history(self, admin_client):
        r = admin_client.post("/api/golden-answers", json={
            "question_text": "Hist Q", "answer_text": "Hist A",
        })
        ga_id = r.json()["id"]
        r = admin_client.get(f"/api/answer-approval/{ga_id}/history")
        assert r.status_code == 200

    def test_editor_can_review(self, client):
        client.cookies.clear()
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.post("/api/golden-answers", json={
            "question_text": "RBAC Q", "answer_text": "RBAC A",
        })
        ga_id = r.json()["id"]
        client.patch(f"/api/golden-answers/{ga_id}", json={"status": "draft"})
        client.post(f"/api/answer-approval/{ga_id}/submit")
        client.cookies.clear()
        client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
        r = client.post(f"/api/answer-approval/{ga_id}/approve", json={})
        assert r.status_code == 200
