"""TC-08-002: unsupported and empty evidence fail with a fixed reason.

A corrupt workbook, a legacy .doc or .xls, an unreadable .docx, and an empty
non-PDF file each end like the PDF failures: a stable reason, a next action,
and a document that is not indexed. The stored text does not include the file
bytes or a path. Synthetic fixtures only. This file is not skipped.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.services.evidence_parser import parse_evidence

MARKER = "synthetic-marker-08002"
_PASS = "synthetic-pass"

# summary, next action. The stored sentence is the two joined by one space.
REASONS = {
    "workbook_corrupt": (
        "Workbook is corrupt or unreadable.",
        "Re-export it as an .xlsx file and upload it again.",
    ),
    "legacy_office": (
        "Legacy .doc and .xls files are not supported.",
        "Save the file as .docx or .xlsx and upload that copy.",
    ),
    "docx_unreadable": (
        "This Word file could not be read.",
        "Re-save it as a .docx file and upload it again.",
    ),
    "empty_evidence": (
        "This file has no extractable text.",
        "Upload a file that contains text.",
    ),
    "pdf_no_text": (
        "This PDF has no text layer; OCR isn't supported.",
        "Upload a text-based PDF, DOCX or XLSX instead.",
    ),
    "pdf_encrypted": (
        "PDF is encrypted or corrupt: it is password-protected.",
        "Upload an unencrypted copy.",
    ),
    "pdf_unreadable": (
        "PDF is encrypted or corrupt: the file could not be read.",
        "Re-export it and upload it again.",
    ),
}

_LEAKS = (
    MARKER,
    _PASS,
    "Traceback",
    "Package not found",
    "BadZipFile",
    "openpyxl",
    "python-docx",
    "/tmp/",
    'File "',
)


def _message(code: str) -> str:
    summary, action = REASONS[code]
    return f"{summary} {action}"


def _corrupt_bytes() -> bytes:
    return f"{MARKER} not a package".encode()


def _legacy_bytes() -> bytes:
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + _corrupt_bytes() + b"\x00" * 64


def _empty_docx() -> bytes:
    from docx import Document

    buf = io.BytesIO()
    Document().save(buf)
    return buf.getvalue()


def _blank_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph("   \t")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _empty_xlsx() -> bytes:
    from openpyxl import Workbook

    buf = io.BytesIO()
    Workbook().save(buf)
    return buf.getvalue()


def _blank_xlsx() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    book.active["A1"] = "   "
    book.active["B2"] = "\n\t"
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _text_xlsx() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    book.active["A1"] = "policy text stays in the sheet"
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _text_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph("policy text stays in the paragraph")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _scan_pdf() -> bytes:
    from app.services.synthetic_pdf import Page, build_pdf

    return build_pdf([Page(image=(50, 50, 495, 700))])


def _broken_pdf() -> bytes:
    return b"%PDF-1.4\n" + _corrupt_bytes() + b"\n%%EOF\n"


def _locked_pdf() -> bytes:
    from pypdf import PdfReader, PdfWriter

    from app.services.synthetic_pdf import Page, TextItem, build_pdf

    base = build_pdf([Page(texts=[TextItem(72, 90, MARKER)])])
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(base)).pages:
        writer.add_page(page)
    writer.encrypt(user_password=_PASS, owner_password="synthetic-owner", algorithm="RC4-128")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


_API_CASES = [
    ("corrupt.xlsx", _corrupt_bytes, "workbook_corrupt"),
    ("legacy.doc", _legacy_bytes, "legacy_office"),
    ("legacy.xls", _legacy_bytes, "legacy_office"),
    ("broken.docx", _corrupt_bytes, "docx_unreadable"),
    ("empty.docx", _empty_docx, "empty_evidence"),
    ("blank.docx", _blank_docx, "empty_evidence"),
    ("empty.xlsx", _empty_xlsx, "empty_evidence"),
    ("blank.xlsx", _blank_xlsx, "empty_evidence"),
    ("empty.txt", lambda: b"", "empty_evidence"),
    ("blank.txt", lambda: b" \n\t ", "empty_evidence"),
    ("scan.pdf", _scan_pdf, "pdf_no_text"),
    ("broken.pdf", _broken_pdf, "pdf_unreadable"),
    ("locked.pdf", _locked_pdf, "pdf_encrypted"),
]


def _assert_clean(text: str, code: str) -> None:
    summary, action = REASONS[code]
    assert text == _message(code)
    assert text.startswith(summary)
    assert action in text
    for leak in _LEAKS:
        assert leak not in text, leak


@pytest.fixture
def storage():
    store: dict[tuple[str, str], bytes] = {}

    def fake_upload(bucket, key, body, **kwargs):
        store[(bucket, key)] = body.read() if hasattr(body, "read") else body
        return key

    def fake_download(bucket, key):
        return store[(bucket, key)]

    from unittest.mock import patch

    with (
        patch("app.services.storage.StorageClient.upload", side_effect=fake_upload),
        patch("app.services.storage.StorageClient.download", side_effect=fake_download),
    ):
        yield store


def _run_worker_on(job_id: int, monkeypatch) -> None:
    import time

    from app import worker
    from app.models import Job, JobStatus

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


def _login(client) -> None:
    response = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(("filename", "build", "code"), _API_CASES, ids=[c[0] for c in _API_CASES])
def test_format_failure_is_not_indexed(
    filename, build, code, client, storage, monkeypatch, db_session
):
    from unittest.mock import patch

    from app.models import Chunk

    _login(client)
    payload = build()
    with patch("app.services.index_service.embed_texts") as embed:
        uploaded = client.post(
            "/api/documents/upload",
            data={"workspace_id": "1"},
            files={"file": (filename, payload, "application/octet-stream")},
        )
        assert uploaded.status_code == 200, uploaded.text
        doc_id, job_id = uploaded.json()["id"], uploaded.json()["job_id"]
        _run_worker_on(job_id, monkeypatch)
        embed.assert_not_called()

    job = client.get(f"/api/jobs/{job_id}?workspace_id=1")
    assert job.status_code == 200, job.text
    body = job.json()
    assert body["kind"] == "index_document"
    assert body["status"] == "failed"
    assert body["error_code"] == "bad_input"
    assert body["retryable"] is False
    _assert_clean(body["error"], code)
    detail = body.get("error_detail") or {}
    assert MARKER not in (detail.get("message") or "")

    listed = client.get("/api/documents?workspace_id=1")
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json() if item["id"] == doc_id)
    assert row["status"] == "failed"
    assert row["status"] != "indexed"
    _assert_clean(row["index_error"], code)

    db_session.expire_all()
    assert db_session.query(Chunk).filter(Chunk.document_id == doc_id).count() == 0

    for path in (
        f"/api/jobs/{job_id}?workspace_id=2",
        "/api/documents?workspace_id=2",
        f"/api/documents/{doc_id}/content?workspace_id=2",
    ):
        denied = client.get(path)
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"] == "Access denied"
        assert MARKER not in denied.text
        assert _message(code) not in denied.text


def test_legacy_office_ignores_installed_libraries(tmp_path, monkeypatch):
    import docx
    import openpyxl

    def boom(*args, **kwargs):
        raise RuntimeError(f"leak {tmp_path} {MARKER}")

    monkeypatch.setattr(docx, "Document", boom)
    monkeypatch.setattr(openpyxl, "load_workbook", boom)
    for name in ("legacy.doc", "legacy.xls"):
        path = tmp_path / name
        path.write_bytes(_legacy_bytes())
        with pytest.raises(Exception) as caught:
            parse_evidence(path)
        err = caught.value
        assert getattr(err, "code", None) == "legacy_office"
        assert getattr(err, "next_action", None) == REASONS["legacy_office"][1]
        _assert_clean(str(err), "legacy_office")
        assert str(tmp_path) not in str(err)


def test_legacy_office_ignores_a_missing_library(tmp_path, monkeypatch):
    import builtins
    import sys

    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "docx" or name.startswith("docx.") or name == "openpyxl":
            raise ImportError(f"missing {name} {MARKER}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    for module in ("docx", "openpyxl"):
        monkeypatch.delitem(sys.modules, module, raising=False)
    for name in ("legacy.doc", "legacy.xls"):
        path = tmp_path / name
        path.write_bytes(_legacy_bytes())
        with pytest.raises(Exception) as caught:
            parse_evidence(path)
        _assert_clean(str(caught.value), "legacy_office")
        assert "missing" not in str(caught.value)


def test_corrupt_workbook_hides_the_bytes(tmp_path):
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(_corrupt_bytes())
    with pytest.raises(Exception) as caught:
        parse_evidence(path)
    assert getattr(caught.value, "code", None) == "workbook_corrupt"
    _assert_clean(str(caught.value), "workbook_corrupt")
    assert str(tmp_path) not in str(caught.value)


def test_corrupt_docx_hides_the_path(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(_corrupt_bytes())
    with pytest.raises(Exception) as caught:
        parse_evidence(path)
    assert getattr(caught.value, "code", None) == "docx_unreadable"
    _assert_clean(str(caught.value), "docx_unreadable")
    assert str(tmp_path) not in str(caught.value)


def test_empty_files_have_no_items(tmp_path):
    samples = {
        "empty.docx": _empty_docx(),
        "blank.docx": _blank_docx(),
        "empty.xlsx": _empty_xlsx(),
        "blank.xlsx": _blank_xlsx(),
        "empty.txt": b"",
        "blank.txt": b" \n\t ",
        "empty.csv": b"",
        "blank.csv": b" \n,\n ",
    }
    for name, payload in samples.items():
        path = tmp_path / name
        path.write_bytes(payload)
        assert parse_evidence(path) == [], name


def test_text_files_still_parse(tmp_path):
    sheet = tmp_path / "policy.xlsx"
    sheet.write_bytes(_text_xlsx())
    items = parse_evidence(sheet)
    assert any("policy text stays in the sheet" in item["text"] for item in items)
    word = tmp_path / "policy.docx"
    word.write_bytes(_text_docx())
    words = parse_evidence(word)
    assert any("policy text stays in the paragraph" in item["text"] for item in words)
    note = tmp_path / "policy.txt"
    note.write_text("plain synthetic text", encoding="utf-8")
    assert parse_evidence(note) == [{"text": "plain synthetic text"}]


def test_stored_csv_and_unknown_bytes_are_not_indexed(client, db_session):
    from app.models import Chunk, Document
    from app.services.file_service import FileService
    from app.services.index_service import index_document

    _login(client)

    class _Store:
        bucket_raw = "raw"

        def __init__(self):
            self.objects: dict[tuple[str, str], bytes] = {}

        def download(self, bucket, key):
            return self.objects[(bucket, key)]

    samples = {
        "empty.csv": b"",
        "words.csv": f"{MARKER},alpha,beta\n".encode(),
        "empty.rtf": b"",
        "words.rtf": f"{{\\rtf1 {MARKER}}}".encode(),
    }
    for name, payload in samples.items():
        store = _Store()
        key = f"raw/1/{name}"
        store.objects[("raw", key)] = payload
        doc = Document(
            workspace_id=1,
            storage_key=key,
            filename=name,
            status="uploaded",
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)
        with pytest.raises(Exception) as caught:
            index_document(db_session, doc.id, store, FileService(store))
        db_session.expire_all()
        stored = db_session.get(Document, doc.id)
        assert stored.status == "failed", name
        assert stored.status != "indexed"
        _assert_clean(stored.index_error, "empty_evidence")
        _assert_clean(str(caught.value), "empty_evidence")
        assert db_session.query(Chunk).filter(Chunk.document_id == doc.id).count() == 0
        db_session.delete(stored)
        db_session.commit()


def test_csv_upload_is_refused_and_not_indexed(client, storage):
    _login(client)
    before = client.get("/api/documents?workspace_id=1")
    assert before.status_code == 200, before.text
    ids = {item["id"] for item in before.json()}
    refused = client.post(
        "/api/documents/upload",
        data={"workspace_id": "1"},
        files={"file": ("notes.csv", f"{MARKER},a,b\n".encode(), "text/csv")},
    )
    assert refused.status_code == 400, refused.text
    assert MARKER not in refused.text
    assert "indexed" not in refused.text.lower()
    after = client.get("/api/documents?workspace_id=1")
    assert after.status_code == 200, after.text
    assert {item["id"] for item in after.json()} == ids


def test_reason_codes_match_the_module():
    from app.services.evidence_format import (
        DocxUnreadableError,
        EmptyEvidenceError,
        LegacyOfficeError,
        WorkbookCorruptError,
    )
    from app.services.pdf_text import ENCRYPTED_MESSAGE as encrypted
    from app.services.pdf_text import NO_TEXT_MESSAGE as no_text
    from app.services.pdf_text import UNREADABLE_MESSAGE as unreadable

    classes = {
        "workbook_corrupt": WorkbookCorruptError,
        "legacy_office": LegacyOfficeError,
        "docx_unreadable": DocxUnreadableError,
        "empty_evidence": EmptyEvidenceError,
    }
    for code, cls in classes.items():
        err = cls()
        assert err.code == code
        assert err.next_action == REASONS[code][1]
        _assert_clean(str(err), code)
        assert err.detail is None
    assert _message("pdf_no_text") == no_text
    assert _message("pdf_encrypted") == encrypted
    assert _message("pdf_unreadable") == unreadable


def test_messages_do_not_embed_a_caller_path(tmp_path: Path):
    from app.services.evidence_format import LegacyOfficeError

    err = LegacyOfficeError(detail=f"{tmp_path}/{MARKER}")
    _assert_clean(str(err), "legacy_office")
    assert err.detail is not None
    assert MARKER not in str(err)
