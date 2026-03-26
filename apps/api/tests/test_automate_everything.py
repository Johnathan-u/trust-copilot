"""Automate Everything: setting persistence, auto-trigger, needs_review evaluation, notifications, audit."""

import json

import pytest
from fastapi.testclient import TestClient


def _login_admin(client: TestClient) -> dict:
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1
        ).first()
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200
    return r.json()


def _set_automation(enabled: bool):
    from app.core.database import SessionLocal
    from app.models.workspace import Workspace
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).first()
        if ws:
            ws.ai_automate_everything = enabled
            db.commit()
    finally:
        db.close()


def _get_audit_events(action: str, workspace_id: int = 1) -> list:
    from app.core.database import SessionLocal
    from app.models import AuditEvent
    db = SessionLocal()
    try:
        return db.query(AuditEvent).filter(
            AuditEvent.action == action, AuditEvent.workspace_id == workspace_id
        ).order_by(AuditEvent.occurred_at.desc()).limit(5).all()
    finally:
        db.close()


def _cleanup_automation_audit():
    from app.core.database import SessionLocal
    from app.models import AuditEvent
    db = SessionLocal()
    try:
        db.query(AuditEvent).filter(AuditEvent.action.like("automation.%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Setting persistence
# ---------------------------------------------------------------------------

class TestSettingPersistence:
    def test_enable_automation(self, client: TestClient) -> None:
        _login_admin(client)
        _set_automation(False)
        r = client.patch("/api/workspaces/current", json={"ai_automate_everything": True})
        assert r.status_code == 200
        assert r.json()["ai_automate_everything"] is True

    def test_disable_automation(self, client: TestClient) -> None:
        _login_admin(client)
        _set_automation(True)
        r = client.patch("/api/workspaces/current", json={"ai_automate_everything": False})
        assert r.status_code == 200
        assert r.json()["ai_automate_everything"] is False

    def test_get_shows_automation_state(self, client: TestClient) -> None:
        _login_admin(client)
        _set_automation(True)
        r = client.get("/api/workspaces/current")
        assert r.status_code == 200
        assert r.json()["ai_automate_everything"] is True
        _set_automation(False)

    def test_non_admin_cannot_set(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
        orig = mem.role
        mem.role = "editor"
        db.commit()
        db.close()
        try:
            client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
            r = client.patch("/api/workspaces/current", json={"ai_automate_everything": True})
            assert r.status_code == 403
        finally:
            db2 = SessionLocal()
            m2 = db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
            m2.role = orig
            db2.commit()
            db2.close()


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

class TestAutomationAudit:
    def test_enable_creates_audit_event(self, client: TestClient) -> None:
        _login_admin(client)
        _set_automation(False)
        _cleanup_automation_audit()
        client.patch("/api/workspaces/current", json={"ai_automate_everything": True})
        events = _get_audit_events("automation.enabled")
        assert len(events) > 0
        _set_automation(False)

    def test_disable_creates_audit_event(self, client: TestClient) -> None:
        _login_admin(client)
        _set_automation(True)
        _cleanup_automation_audit()
        client.patch("/api/workspaces/current", json={"ai_automate_everything": False})
        events = _get_audit_events("automation.disabled")
        assert len(events) > 0


# ---------------------------------------------------------------------------
# Auto-trigger logic (unit test)
# ---------------------------------------------------------------------------

class TestAutoTrigger:
    def test_no_trigger_when_disabled(self) -> None:
        from app.core.database import SessionLocal
        from app.services.automation_service import maybe_auto_generate
        from app.models import Job, JobStatus, Questionnaire
        _set_automation(False)
        db = SessionLocal()
        try:
            qnr = db.query(Questionnaire).filter(Questionnaire.workspace_id == 1).first()
            if not qnr:
                return
            mock_job = Job(workspace_id=1, kind="parse_questionnaire", status=JobStatus.COMPLETED.value)
            payload = {"questionnaire_id": qnr.id}
            initial_count = db.query(Job).filter(Job.kind == "generate_answers", Job.workspace_id == 1).count()
            maybe_auto_generate(db, mock_job, payload)
            after_count = db.query(Job).filter(Job.kind == "generate_answers", Job.workspace_id == 1).count()
            assert after_count == initial_count
        finally:
            db.close()

    def test_trigger_when_enabled(self) -> None:
        from app.core.database import SessionLocal
        from app.services.automation_service import maybe_auto_generate
        from app.models import Job, JobStatus, Question, Questionnaire
        _set_automation(True)
        db = SessionLocal()
        try:
            qnr = db.query(Questionnaire).filter(Questionnaire.workspace_id == 1).first()
            if not qnr:
                qnr = Questionnaire(workspace_id=1, filename="auto_test.xlsx", status="parsed")
                db.add(qnr)
                db.commit()
                db.refresh(qnr)
            if db.query(Question).filter(Question.questionnaire_id == qnr.id).count() == 0:
                db.add(Question(questionnaire_id=qnr.id, text="Auto-test question?"))
                db.commit()
            # Clean up any existing queued generate jobs for this qnr
            db.query(Job).filter(
                Job.kind == "generate_answers",
                Job.workspace_id == 1,
                Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
            ).delete(synchronize_session=False)
            db.commit()
            mock_job = Job(workspace_id=1, kind="parse_questionnaire", status=JobStatus.COMPLETED.value)
            payload = {"questionnaire_id": qnr.id}
            maybe_auto_generate(db, mock_job, payload)
            gen_job = db.query(Job).filter(
                Job.kind == "generate_answers",
                Job.workspace_id == 1,
                Job.status == JobStatus.QUEUED.value,
            ).order_by(Job.created_at.desc()).first()
            assert gen_job is not None
            p = json.loads(gen_job.payload)
            assert p["questionnaire_id"] == qnr.id
            # Clean up
            db.delete(gen_job)
            db.commit()
        finally:
            _set_automation(False)
            db.close()


# ---------------------------------------------------------------------------
# Evaluation logic (unit test)
# ---------------------------------------------------------------------------

class TestEvaluation:
    def test_needs_review_when_insufficient(self) -> None:
        from app.core.database import SessionLocal
        from app.services.automation_service import evaluate_generation_result
        from app.models import Job, JobStatus, Questionnaire, Question, Answer, InAppNotification
        _set_automation(True)
        _cleanup_automation_audit()
        db = SessionLocal()
        try:
            qnr = db.query(Questionnaire).filter(Questionnaire.workspace_id == 1).first()
            if not qnr:
                _set_automation(False)
                return
            questions = db.query(Question).filter(Question.questionnaire_id == qnr.id).all()
            if not questions:
                _set_automation(False)
                return
            # Set first answer to insufficient
            first_q = questions[0]
            ans = db.query(Answer).filter(Answer.question_id == first_q.id).first()
            if ans:
                orig_text, orig_conf = ans.text, ans.confidence
                ans.text = "Insufficient evidence"
                ans.confidence = 0
                db.commit()
            else:
                ans = Answer(question_id=first_q.id, text="Insufficient evidence", status="draft", confidence=0)
                db.add(ans)
                db.commit()
                orig_text, orig_conf = None, None

            mock_job = Job(workspace_id=1, kind="generate_answers", status=JobStatus.COMPLETED.value)
            payload = {"questionnaire_id": qnr.id, "workspace_id": 1}

            # Clear notifications before eval
            db.query(InAppNotification).filter(InAppNotification.workspace_id == 1, InAppNotification.title.like("%Review needed%")).delete(synchronize_session=False)
            db.commit()

            evaluate_generation_result(db, mock_job, payload)

            events = _get_audit_events("automation.run_needs_review")
            assert len(events) > 0

            notifs = db.query(InAppNotification).filter(
                InAppNotification.workspace_id == 1,
                InAppNotification.title.like("%Review needed%"),
            ).all()
            assert len(notifs) > 0

            # Restore
            if orig_text is not None:
                ans.text = orig_text
                ans.confidence = orig_conf
                db.commit()
        finally:
            _set_automation(False)
            db.close()

    def test_completed_when_all_sufficient(self) -> None:
        from unittest.mock import patch as _patch
        from app.core.database import SessionLocal
        from app.services.automation_service import evaluate_generation_result
        from app.models import Job, JobStatus, Questionnaire, Question, Answer
        _cleanup_automation_audit()
        db = SessionLocal()
        try:
            qnr = db.query(Questionnaire).filter(Questionnaire.workspace_id == 1).first()
            if not qnr:
                pytest.skip("no questionnaire for workspace 1")
            questions = db.query(Question).filter(Question.questionnaire_id == qnr.id).all()
            if not questions:
                pytest.skip("no questions")
            for q in questions:
                ans = db.query(Answer).filter(Answer.question_id == q.id).first()
                if not ans:
                    db.add(Answer(question_id=q.id, text="Proper answer", status="draft", confidence=80))
                else:
                    ans.text = "Proper answer"
                    ans.status = "draft"
                    ans.confidence = 80
            db.commit()

            mock_job = Job(workspace_id=1, kind="generate_answers", status=JobStatus.COMPLETED.value)
            payload = {"questionnaire_id": qnr.id, "workspace_id": 1}
            with _patch("app.services.automation_service._is_automation_enabled", return_value=True):
                evaluate_generation_result(db, mock_job, payload)

            events = _get_audit_events("automation.run_completed")
            assert len(events) > 0
        finally:
            db.close()
