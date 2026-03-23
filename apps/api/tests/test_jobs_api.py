"""P07: Job status API for UI polling (GET /api/jobs/{id})."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models import Job


@pytest.mark.integration
def test_get_job_requires_auth(client: TestClient) -> None:
    """P07: Unauthenticated job poll returns 401."""
    r = client.get("/api/jobs/1?workspace_id=1")
    assert r.status_code == 401


def test_get_job_workspace_mismatch_returns_403(client: TestClient) -> None:
    """P07: Query workspace_id must match session workspace."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/jobs/1?workspace_id=2")
    assert r.status_code == 403
    assert "denied" in (r.json().get("detail") or "").lower()


def test_get_job_not_found_returns_404(client: TestClient) -> None:
    """P07: Unknown job id in correct workspace returns 404."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/jobs/999999999?workspace_id=1")
    assert r.status_code == 404


def test_get_job_returns_shape(client: TestClient) -> None:
    """P07: Happy path returns id, kind, status, attempt, error, timestamps."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    session = SessionLocal()
    try:
        job = Job(
            workspace_id=1,
            kind="index_document",
            status="queued",
            payload=json.dumps({"document_id": 1}),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        jid = job.id
    finally:
        session.close()

    r = client.get(f"/api/jobs/{jid}?workspace_id=1")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == jid
    assert data["kind"] == "index_document"
    assert data["status"] == "queued"
    assert "attempt" in data
    assert "error" in data
    assert "result" in data
    assert "created_at" in data
    assert "completed_at" in data

    session = SessionLocal()
    try:
        session.query(Job).filter(Job.id == jid).delete()
        session.commit()
    finally:
        session.close()
