"""P1 Multi-Tenant Hardening Tests — quotas, fair scheduling, defense-in-depth."""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

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


def _cleanup_usage(ws=1):
    from app.core.database import SessionLocal
    from app.models.workspace_quota import WorkspaceUsage, WorkspaceQuota
    db = SessionLocal()
    try:
        db.query(WorkspaceUsage).filter(WorkspaceUsage.workspace_id == ws).delete()
        db.query(WorkspaceQuota).filter(WorkspaceQuota.workspace_id == ws).delete()
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Quota service unit tests
# ---------------------------------------------------------------------------

class TestQuotaService:
    def test_default_quotas_returned(self, client: TestClient) -> None:
        _cleanup_usage()
        from app.core.database import SessionLocal
        from app.services.quota_service import get_quota_limit
        db = SessionLocal()
        try:
            assert get_quota_limit(db, 1, "ai_jobs") == 10
            assert get_quota_limit(db, 1, "exports") == 30
            assert get_quota_limit(db, 1, "documents") == 500
        finally:
            db.close()

    def test_custom_quota_overrides_default(self, client: TestClient) -> None:
        _cleanup_usage()
        from app.core.database import SessionLocal
        from app.models.workspace_quota import WorkspaceQuota
        from app.services.quota_service import get_quota_limit
        db = SessionLocal()
        try:
            db.add(WorkspaceQuota(workspace_id=1, max_ai_jobs_per_hour=5, max_exports_per_hour=3))
            db.commit()
            assert get_quota_limit(db, 1, "ai_jobs") == 5
            assert get_quota_limit(db, 1, "exports") == 3
        finally:
            db.close()
        _cleanup_usage()

    def test_record_and_check_increments(self, client: TestClient) -> None:
        _cleanup_usage()
        from app.core.database import SessionLocal
        from app.services.quota_service import record_and_check, get_current_usage
        db = SessionLocal()
        try:
            allowed, current, limit = record_and_check(db, 1, "ai_jobs")
            assert allowed is True
            assert current == 1
            db.commit()
            assert get_current_usage(db, 1, "ai_jobs") == 1
        finally:
            db.close()
        _cleanup_usage()

    def test_quota_enforcement_blocks_at_limit(self, client: TestClient) -> None:
        _cleanup_usage()
        from app.core.database import SessionLocal
        from app.models.workspace_quota import WorkspaceQuota
        from app.services.quota_service import record_usage, check_quota
        db = SessionLocal()
        try:
            db.add(WorkspaceQuota(workspace_id=1, max_ai_jobs_per_hour=3))
            db.commit()
            for _ in range(3):
                record_usage(db, 1, "ai_jobs")
            db.commit()
            allowed, current, limit = check_quota(db, 1, "ai_jobs")
            assert allowed is False
            assert current == 3
            assert limit == 3
        finally:
            db.close()
        _cleanup_usage()

    def test_quota_scoped_to_workspace(self, client: TestClient) -> None:
        _cleanup_usage()
        _cleanup_usage(2)
        from app.core.database import SessionLocal
        from app.services.quota_service import record_usage, get_current_usage
        db = SessionLocal()
        try:
            record_usage(db, 1, "ai_jobs", 5)
            db.commit()
            assert get_current_usage(db, 1, "ai_jobs") == 5
            assert get_current_usage(db, 2, "ai_jobs") == 0
        finally:
            db.close()
        _cleanup_usage()

    def test_cleanup_old_usage(self, client: TestClient) -> None:
        _cleanup_usage()
        from app.core.database import SessionLocal
        from app.models.workspace_quota import WorkspaceUsage
        from app.services.quota_service import cleanup_old_usage
        from datetime import timedelta
        db = SessionLocal()
        try:
            old_window = datetime.now(timezone.utc) - timedelta(hours=48)
            db.add(WorkspaceUsage(workspace_id=1, resource_type="ai_jobs", window_start=old_window, count=10))
            db.commit()
            cleaned = cleanup_old_usage(db)
            db.commit()
            assert cleaned >= 1
        finally:
            db.close()
        _cleanup_usage()


# ---------------------------------------------------------------------------
# Worker fair scheduling tests
# ---------------------------------------------------------------------------

class TestFairScheduling:
    def test_claim_job_rotates_workspaces(self, client: TestClient) -> None:
        """After claiming a job from WS1, next claim should prefer other workspaces."""
        from app.core.database import SessionLocal
        from app.models import Job, JobStatus
        import app.worker as worker

        db = SessionLocal()
        try:
            db.query(Job).filter(Job.status == JobStatus.QUEUED.value).delete()
            db.commit()

            for i in range(3):
                db.add(Job(workspace_id=1, kind="parse_questionnaire", status=JobStatus.QUEUED.value,
                           payload=json.dumps({"questionnaire_id": 100 + i, "storage_key": "test.xlsx"}),
                           created_at=datetime.utcnow()))
            db.add(Job(workspace_id=2, kind="parse_questionnaire", status=JobStatus.QUEUED.value,
                       payload=json.dumps({"questionnaire_id": 200, "storage_key": "test.xlsx"}),
                       created_at=datetime.utcnow()))
            db.commit()

            worker._last_claimed_workspace_id = None
            job1 = worker.claim_job(db)
            assert job1 is not None
            ws1 = job1.workspace_id

            job2 = worker.claim_job(db)
            assert job2 is not None
            if ws1 == 1:
                assert job2.workspace_id == 2, "Should rotate to workspace 2"
            else:
                assert job2.workspace_id == 1, "Should rotate to workspace 1"

            db.query(Job).filter(Job.id.in_([job1.id, job2.id])).delete()
            db.query(Job).filter(Job.status == JobStatus.QUEUED.value, Job.kind == "parse_questionnaire").delete()
            db.commit()
        finally:
            worker._last_claimed_workspace_id = None
            db.close()

    def test_claim_falls_back_when_only_one_workspace(self, client: TestClient) -> None:
        """When all queued jobs are from one workspace, still claims them."""
        from app.core.database import SessionLocal
        from app.models import Job, JobStatus
        import app.worker as worker

        db = SessionLocal()
        try:
            db.query(Job).filter(Job.status == JobStatus.QUEUED.value).delete()
            db.commit()

            db.add(Job(workspace_id=1, kind="parse_questionnaire", status=JobStatus.QUEUED.value,
                       payload=json.dumps({"questionnaire_id": 999, "storage_key": "test.xlsx"}),
                       created_at=datetime.utcnow()))
            db.commit()

            worker._last_claimed_workspace_id = 1
            job = worker.claim_job(db)
            assert job is not None
            assert job.workspace_id == 1

            db.query(Job).filter(Job.id == job.id).delete()
            db.commit()
        finally:
            worker._last_claimed_workspace_id = None
            db.close()


# ---------------------------------------------------------------------------
# Defense-in-depth workspace cross-checks
# ---------------------------------------------------------------------------

class TestWorkerDefenseInDepth:
    def test_parse_questionnaire_rejects_workspace_mismatch(self, client: TestClient) -> None:
        from app.models import Job
        import app.worker as worker

        mock_job = MagicMock(spec=Job)
        mock_job.workspace_id = 1

        mock_qnr = MagicMock()
        mock_qnr.workspace_id = 2

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_qnr

        with pytest.raises(ValueError, match="workspace mismatch"):
            worker.run_parse_questionnaire(
                mock_job, mock_session,
                {"questionnaire_id": 1, "storage_key": "test.xlsx"}
            )

    def test_generate_answers_rejects_workspace_mismatch(self, client: TestClient) -> None:
        from app.models import Job
        import app.worker as worker

        mock_job = MagicMock(spec=Job)
        mock_job.workspace_id = 1

        with pytest.raises(ValueError, match="workspace_id"):
            worker.run_generate_answers(
                mock_job, MagicMock(),
                {"questionnaire_id": 1, "workspace_id": 2}
            )


# ---------------------------------------------------------------------------
# API quota enforcement tests
# ---------------------------------------------------------------------------

class TestAPIQuotaEnforcement:
    def test_generate_answers_blocked_at_quota(self, client: TestClient) -> None:
        _cleanup_usage()
        _login_admin(client)

        from app.core.database import SessionLocal
        from app.models.workspace_quota import WorkspaceQuota
        from app.services.quota_service import record_usage
        db = SessionLocal()
        try:
            db.add(WorkspaceQuota(workspace_id=1, max_ai_jobs_per_hour=2))
            db.commit()
            for _ in range(2):
                record_usage(db, 1, "ai_jobs")
            db.commit()
        finally:
            db.close()

        r = client.post("/api/exports/generate/1?workspace_id=1")
        assert r.status_code == 429
        assert "quota exceeded" in r.json()["detail"].lower()
        _cleanup_usage()

    def test_export_blocked_at_quota(self, client: TestClient) -> None:
        _cleanup_usage()
        _login_admin(client)

        from app.core.database import SessionLocal
        from app.models.workspace_quota import WorkspaceQuota
        from app.services.quota_service import record_usage
        db = SessionLocal()
        try:
            db.add(WorkspaceQuota(workspace_id=1, max_exports_per_hour=1))
            db.commit()
            record_usage(db, 1, "exports")
            db.commit()
        finally:
            db.close()

        r = client.post("/api/exports/export/1?workspace_id=1")
        assert r.status_code == 429
        assert "quota exceeded" in r.json()["detail"].lower()
        _cleanup_usage()


# ---------------------------------------------------------------------------
# Model creation tests
# ---------------------------------------------------------------------------

class TestQuotaModels:
    def test_workspace_quota_model(self, client: TestClient) -> None:
        _cleanup_usage()
        from app.core.database import SessionLocal
        from app.models.workspace_quota import WorkspaceQuota
        db = SessionLocal()
        try:
            q = WorkspaceQuota(workspace_id=1, max_documents=100)
            db.add(q)
            db.commit()
            db.refresh(q)
            assert q.id is not None
            assert q.max_documents == 100
            assert q.max_ai_jobs_per_hour == 10
        finally:
            db.close()
        _cleanup_usage()

    def test_workspace_usage_model(self, client: TestClient) -> None:
        _cleanup_usage()
        from app.core.database import SessionLocal
        from app.models.workspace_quota import WorkspaceUsage
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            u = WorkspaceUsage(workspace_id=1, resource_type="test", window_start=now, count=5)
            db.add(u)
            db.commit()
            db.refresh(u)
            assert u.id is not None
            assert u.count == 5
        finally:
            db.close()
        _cleanup_usage()
