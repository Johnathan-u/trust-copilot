"""TEST-02: Integration test covering upload to parse to review."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models import Job, Questionnaire
from app.worker import run_parse_questionnaire


@pytest.mark.integration
def test_upload_parse_review_flow(client: TestClient) -> None:
    """Upload questionnaire -> parse job runs -> review data available."""
    in_memory_store: dict[tuple[str, str], bytes] = {}

    def fake_upload(bucket: str, key: str, body, **kwargs) -> str:
        content = body.read() if hasattr(body, "read") else body
        in_memory_store[(bucket, key)] = content
        return key

    def fake_download(bucket: str, key: str) -> bytes:
        return in_memory_store[(bucket, key)]

    with patch("app.services.storage.StorageClient.upload", side_effect=fake_upload):
        with patch("app.services.storage.StorageClient.download", side_effect=fake_download):
            # 1. Login
            r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
            assert r.status_code == 200

            # 2. Upload questionnaire
            fixture = Path(__file__).parent / "fixtures" / "questionnaires" / "simple_soc2.xlsx"
            assert fixture.exists()
            with open(fixture, "rb") as f:
                r = client.post(
                    "/api/questionnaires/upload",
                    data={"workspace_id": "1"},
                    files={"file": ("simple_soc2.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                )
            assert r.status_code == 200
            data = r.json()
            qnr_id = data["id"]
            job_id = data["job_id"]

            # 3. Run parse job (worker logic)
            session = SessionLocal()
            try:
                job = session.query(Job).filter(Job.id == job_id).first()
                assert job and job.kind == "parse_questionnaire"
                payload = json.loads(job.payload)
                run_parse_questionnaire(job, session, payload)
                session.commit()
            finally:
                session.close()

            # 4. Review: fetch questionnaire with questions
            r = client.get(f"/api/questionnaires/{qnr_id}?workspace_id=1")
            assert r.status_code == 200
            qnr = r.json()
            assert qnr["status"] == "parsed"
            assert len(qnr["questions"]) >= 1
            assert any("security" in (q.get("text") or "").lower() for q in qnr["questions"])
