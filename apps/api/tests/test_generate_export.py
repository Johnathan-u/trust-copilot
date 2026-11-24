"""TEST-03: Integration test for generate to export flow."""

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models import Answer, ExportRecord, Job, JobStatus, Question, Questionnaire  # noqa: F401
from app.worker import run_export, run_parse_questionnaire


@pytest.mark.integration
def test_generate_to_export_flow(client: TestClient) -> None:
    """Parse questionnaire -> create answers -> export job -> export record and download URL."""
    in_memory_store: dict[tuple[str, str], dict] = {}

    def fake_upload(bucket: str, key: str, body, **kwargs) -> str:
        content = body.read() if hasattr(body, "read") else body
        written = {
            str(name): str(value)
            for name, value in dict(kwargs.get("metadata") or {}).items()
            if isinstance(name, str)
        }
        content_type = kwargs.get("content_type")
        if isinstance(content_type, str) and content_type:
            written["content-type"] = content_type
        in_memory_store[(bucket, key)] = {"body": bytes(content), "metadata": written}
        return key

    def _stored(bucket: str, key: str) -> dict | None:
        return in_memory_store.get((bucket, key))

    def fake_download(bucket: str, key: str) -> bytes:
        item = _stored(bucket, key)
        if item is None:
            return b""
        return item["body"]

    def fake_exists(bucket: str, key: str) -> bool:
        return (bucket, key) in in_memory_store

    def fake_download_stream(bucket: str, key: str):
        item = _stored(bucket, key)
        body = b"" if item is None else item["body"]
        return io.BytesIO(body)

    def fake_download_checksummed(bucket: str, key: str):
        item = _stored(bucket, key)
        if item is None:
            raise FileNotFoundError(key)
        return item["body"], dict(item["metadata"])

    with patch("app.services.storage.StorageClient.upload", side_effect=fake_upload):
        with patch("app.services.storage.StorageClient.download", side_effect=fake_download):
            with patch("app.services.storage.StorageClient.exists", side_effect=fake_exists):
                with (
                    patch(
                        "app.services.storage.StorageClient.download_stream",
                        side_effect=fake_download_stream,
                    ),
                    patch(
                        "app.services.storage.StorageClient.download_checksummed",
                        side_effect=fake_download_checksummed,
                    ),
                ):
                    r = client.post(
                        "/api/auth/login", json={"email": "demo@trust.local", "password": "j"}
                    )
                    assert r.status_code == 200

                    fixture = (
                        Path(__file__).parent / "fixtures" / "questionnaires" / "simple_soc2.xlsx"
                    )
                    assert fixture.exists()
                    with open(fixture, "rb") as f:
                        r = client.post(
                            "/api/questionnaires/upload",
                            data={"workspace_id": "1"},
                            files={
                                "file": (
                                    "simple_soc2.xlsx",
                                    f,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                )
                            },
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

                        questions = (
                            session.query(Question)
                            .filter(Question.questionnaire_id == qnr_id)
                            .all()
                        )
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

                        recs = (
                            session.query(ExportRecord)
                            .filter(ExportRecord.questionnaire_id == qnr_id)
                            .all()
                        )
                        assert len(recs) >= 1
                        rec = recs[0]
                        assert rec.status == "completed"
                        assert rec.filename
                        assert rec.storage_key
                        assert rec.content_sha256
                        assert rec.object_version
                        assert rec.content_type
                        stored = next(
                            item
                            for (bucket, key), item in in_memory_store.items()
                            if key == rec.storage_key
                        )
                        assert rec.content_sha256 == hashlib.sha256(stored["body"]).hexdigest()
                        assert stored["metadata"].get("sha256") == rec.content_sha256
                        assert stored["metadata"].get("version") == str(rec.object_version)
                        assert stored["metadata"].get("workspace-id") == str(rec.workspace_id)
                        assert stored["metadata"].get("media-type") == rec.content_type
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
