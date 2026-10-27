"""TC-01-003a review follow-up: PDF failures reach the user cleanly, end to end.

Image-only ("no text layer"), password-protected and corrupt/truncated PDFs are
uploaded through the real API (questionnaire upload and evidence document upload),
the queued job is executed by the real worker loop body (``_process_one_job``), and
the result is read back through the API. Each case asserts:

* no 5xx anywhere (upload and status reads are 200);
* the job ends ``failed`` with the fixed, readable message;
* the document / questionnaire is marked ``failed`` with the same message;
* no traceback, file path, temp dir, backend name or backend exception text leaks.

Also: a missing pypdf fails at import / startup (API and worker), not per request.
Synthetic PDFs from tests/pdf_locator only; no network, no model calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.pdf_text import ENCRYPTED_MESSAGE, NO_TEXT_MESSAGE, UNREADABLE_MESSAGE

sys.path.insert(0, str(Path(__file__).parent))
from pdf_locator import corpus  # noqa: E402

API_ROOT = Path(__file__).resolve().parent.parent
_CASES = {c.name: c for c in corpus()}

# corpus case -> message the user must see
EXPECTED = {
    "image_only_scan": NO_TEXT_MESSAGE,
    "encrypted_user_password_required": ENCRYPTED_MESSAGE,
    "corrupt_not_pdf": UNREADABLE_MESSAGE,
    "truncated_pdf": UNREADABLE_MESSAGE,
}

LEAK_MARKERS = (
    "Traceback",
    'File "',
    "Errno",
    tempfile.gettempdir(),
    "/repo/",
    "/app/",
    ".pdf",
    "pypdf",
    "PdfReadError",
    "PdfNoTextError",
    "PdfEncryptedError",
    "PdfUnreadableError",
    "Exception",
)


def _assert_clean(text: str | None, expected: str) -> None:
    assert text == expected
    for marker in LEAK_MARKERS:
        assert marker not in text, f"leaked {marker!r} in {text!r}"


def test_user_messages_are_readable():
    assert NO_TEXT_MESSAGE.startswith("This PDF has no text layer; OCR isn't supported")
    assert ENCRYPTED_MESSAGE.startswith("PDF is encrypted or corrupt")
    assert UNREADABLE_MESSAGE.startswith("PDF is encrypted or corrupt")
    for m in (NO_TEXT_MESSAGE, ENCRYPTED_MESSAGE, UNREADABLE_MESSAGE):
        _assert_clean(m, m)


@pytest.fixture
def storage():
    store: dict[tuple[str, str], bytes] = {}

    def fake_upload(bucket, key, body, **kwargs):
        store[(bucket, key)] = body.read() if hasattr(body, "read") else body
        return key

    def fake_download(bucket, key):
        return store[(bucket, key)]

    with (
        patch("app.services.storage.StorageClient.upload", side_effect=fake_upload),
        patch("app.services.storage.StorageClient.download", side_effect=fake_download),
    ):
        yield store


def _run_worker_on(job_id: int, monkeypatch) -> None:
    """Run the real worker loop body (_process_one_job) on exactly this job."""
    import time

    from app import worker
    from app.models import Job, JobStatus

    # Skip the periodic side tasks; claim only our job (other tests may leave queued jobs).
    monkeypatch.setattr(worker, "last_compliance_webhook_run", time.time())
    monkeypatch.setattr(worker, "last_usage_cleanup_run", time.time())

    def claim_only(session):
        job = session.query(Job).filter(Job.id == job_id).first()
        assert job is not None and job.status == JobStatus.QUEUED.value
        job.status = JobStatus.RUNNING.value
        job.attempt += 1
        session.commit()
        session.refresh(job)
        return job

    monkeypatch.setattr(worker, "claim_job", claim_only)
    assert worker._process_one_job() is True


def _login(client):
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200


def _get_job(client, job_id: int) -> dict:
    r = client.get(f"/api/jobs/{job_id}?workspace_id=1")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("case_name", sorted(EXPECTED))
def test_questionnaire_pdf_failure_is_failed_job_with_readable_message(
    case_name, client, storage, monkeypatch
):
    _login(client)
    pdf = _CASES[case_name].pdf
    r = client.post(
        "/api/questionnaires/upload",
        data={"workspace_id": "1"},
        files={"file": (f"{case_name}.pdf", pdf, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    qnr_id, job_id = r.json()["id"], r.json()["job_id"]

    _run_worker_on(job_id, monkeypatch)

    job = _get_job(client, job_id)
    assert job["kind"] == "parse_questionnaire"
    assert job["status"] == "failed"
    _assert_clean(job["error"], EXPECTED[case_name])

    r = client.get(f"/api/questionnaires/{qnr_id}?workspace_id=1")
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["status"] == "failed"
    assert q["questions"] == []
    _assert_clean(json.loads(q["parse_metadata"])["error"], EXPECTED[case_name])


@pytest.mark.parametrize("case_name", sorted(EXPECTED))
def test_evidence_pdf_failure_is_failed_document_with_readable_message(
    case_name, client, storage, monkeypatch
):
    _login(client)
    pdf = _CASES[case_name].pdf
    with patch("app.services.index_service.embed_texts") as embed:
        r = client.post(
            "/api/documents/upload",
            data={"workspace_id": "1"},
            files={"file": (f"{case_name}.pdf", pdf, "application/pdf")},
        )
        assert r.status_code == 200, r.text
        doc_id, job_id = r.json()["id"], r.json()["job_id"]
        _run_worker_on(job_id, monkeypatch)
        embed.assert_not_called()  # failed before any embedding/model call

    job = _get_job(client, job_id)
    assert job["kind"] == "index_document"
    assert job["status"] == "failed"
    _assert_clean(job["error"], EXPECTED[case_name])

    r = client.get("/api/documents?workspace_id=1")
    assert r.status_code == 200, r.text
    doc = next(d for d in r.json() if d["id"] == doc_id)
    assert doc["status"] == "failed"
    _assert_clean(doc["index_error"], EXPECTED[case_name])


# ---- missing PDF library: fail at import/startup, not per request ----------------


def _import_with_pypdf_blocked(module: str, block: bool = True) -> subprocess.CompletedProcess:
    code = (
        ("import sys; sys.modules['pypdf'] = None\n" if block else "")
        + f"import {module}\n"
        + "print('imported')\n"
    )
    env = {**os.environ, "TRUST_COPILOT_TESTING": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.parametrize("module", ["app.services.pdf_text", "app.worker", "app.main"])
def test_missing_pypdf_fails_at_import_and_startup(module):
    r = _import_with_pypdf_blocked(module)
    assert r.returncode != 0, r.stdout
    assert "imported" not in r.stdout
    assert "ModuleNotFoundError" in r.stderr and "pypdf" in r.stderr, r.stderr[-2000:]


@pytest.mark.parametrize("module", ["app.services.pdf_text", "app.worker"])
def test_modules_import_with_pypdf_present(module):
    r = _import_with_pypdf_blocked(module, block=False)
    assert r.returncode == 0 and "imported" in r.stdout, r.stderr[-2000:]
