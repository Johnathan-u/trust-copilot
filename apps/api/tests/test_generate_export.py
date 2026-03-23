"""TEST-03: Integration test for generate to export flow."""

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models import Answer, ExportRecord, Job, JobStatus, Question, Questionnaire
from app.worker import run_export, run_parse_questionnaire


@pytest.mark.integration
def test_generate_to_export_flow(client: TestClient) -> None:
    """Parse questionnaire -> create answers -> export job -> export record and download URL."""
    in_memory_store: dict[tuple[str, str], bytes] = {}

    def fake_upload(bucket: str, key: str, body, **kwargs) -> str:
        content = body.read() if hasattr(body, "read") else body
        in_memory_store[(bucket, key)] = content
        return key

    def fake_download(bucket: str, key: str) -> bytes:
        return in_memory_store.get((bucket, key), b"")

    def fake_exists(bucket: str, key: str) -> bool:
        return (bucket, key) in in_memory_store

    def fake_download_stream(bucket: str, key: str):
        return io.BytesIO(in_memory_store.get((bucket, key), b""))

    with patch("app.services.storage.StorageClient.upload", side_effect=fake_upload):
        with patch("app.services.storage.StorageClient.download", side_effect=fake_download):
            with patch("app.services.storage.StorageClient.exists", side_effect=fake_exists):
                with patch("app.services.storage.StorageClient.download_stream", side_effect=fake_download_stream):
                    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
                    assert r.status_code == 200

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
                    parse_job_id = data["job_id"]

                    session = SessionLocal()
                    try:
                        job = session.query(Job).filter(Job.id == parse_job_id).first()
                        assert job
                        run_parse_questionnaire(job, session, json.loads(job.payload))
                        session.commit()

                        questions = session.query(Question).filter(Question.questionnaire_id == qnr_id).all()
                        for q in questions:
                            a = Answer(question_id=q.id, text="Test answer", status="approved")
                            session.add(a)
                        session.commit()

                        r = client.post(f"/api/exports/export/{qnr_id}?workspace_id=1")
                        assert r.status_code == 200
                        export_data = r.json()
                        export_job_id = export_data["job_id"]

                        job = session.query(Job).filter(Job.id == export_job_id).first()
                        run_export(job, session, json.loads(job.payload))
                        # Mirror worker: run_export does not set job.status; main loop marks completed.
                        job.status = JobStatus.COMPLETED.value
                        from datetime import datetime, timezone

                        job.completed_at = datetime.now(timezone.utc)
                        session.merge(job)
                        session.commit()

                        recs = session.query(ExportRecord).filter(ExportRecord.questionnaire_id == qnr_id).all()
                        assert len(recs) >= 1
                        rec = recs[0]
                        assert rec.status == "completed"
                        assert rec.filename
                        assert rec.storage_key
                        rec_id = rec.id
                        export_job_id_for_poll = export_job_id
                    finally:
                        session.close()

                    # P07/P08: job polling reflects completed export worker run
                    r_job = client.get(f"/api/jobs/{export_job_id_for_poll}?workspace_id=1")
                    assert r_job.status_code == 200
                    job_payload = r_job.json()
                    assert job_payload["kind"] == "export"
                    assert job_payload["status"] == "completed"

                    r = client.get(f"/api/exports/records/{rec_id}/download?workspace_id=1")
                    assert r.status_code == 200
                    assert "attachment" in (r.headers.get("Content-Disposition") or "")
                    assert r.content
