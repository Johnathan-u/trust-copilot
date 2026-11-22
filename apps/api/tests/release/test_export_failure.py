"""TC-13-005: export failures stay on the requested format.

XLSX render failures and storage failures become a failed export record with a
fixed error code and message. They must not be rewritten as a DOCX (or any
other format). A DOCX pack is produced only when the client asked for DOCX.
Successful downloads use that file's content type and filename extension, and
the sha256 stored with the export matches the bytes.

Stale question-cell mapping (TC-09-002, PR #239) is not covered here. That
conflict response is deferred until the mapping change lands. This module does
not need a database.
"""

from __future__ import annotations

import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

pytestmark = pytest.mark.unit

XLSX_FAILED = "export_xlsx_failed"
XLSX_FAILED_MESSAGE = "The XLSX export could not be written. No substitute file was produced."
DOCX_FAILED = "export_docx_failed"
DOCX_FAILED_MESSAGE = "The DOCX export could not be written. No substitute file was produced."
STORAGE_FAILED = "export_storage_failed"
STORAGE_FAILED_MESSAGE = "The export could not be stored. No substitute file was produced."
MAPPING_STALE = "export_mapping_stale"
MAPPING_STALE_MESSAGE = (
    "The workbook no longer matches the stored cell mapping. No answers were written."
)
_MAPPED_QUESTION = "Do you encrypt data at rest?"
_MAPPED_ANSWER = "Approved encryption control PRIVATE-ANSWER"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SHA256_HEADER = "x-content-sha256"
_PRIVATE = "PRIVATE s3://secret-bucket/customer-key SignatureDoesNotMatch"


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    wb.active.title = "Security"
    wb.active["A1"] = "Question"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Query:
    def __init__(self, value):
        self._value = value

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def first(self):
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def all(self):
        if self._value is None:
            return []
        if isinstance(self._value, list):
            return list(self._value)
        return [self._value]


class _Session:
    def __init__(self, rows: dict):
        self._rows = rows
        self.added: list = []

    def query(self, model):
        return _Query(self._rows.get(model))

    def add(self, obj) -> None:
        self.added.append(obj)

    def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1

    def rollback(self) -> None:
        return None

    def commit(self) -> None:
        return None


class _Store:
    def __init__(self, blob: bytes):
        self.blob = blob
        self.bucket_raw = "raw"
        self.bucket_exports = "exports"
        self.uploads: list[tuple[str, bytes, str | None]] = []

    def download(self, bucket: str, key: str) -> bytes:
        return self.blob

    def upload(self, bucket: str, key: str, body, content_type: str | None = None) -> str:
        data = body.read() if hasattr(body, "read") else body
        self.uploads.append((key, bytes(data), content_type))
        return key

    def exists(self, bucket: str, key: str) -> bool:
        return any(item[0] == key for item in self.uploads) or key.startswith("exports/")

    def download_stream(self, bucket: str, key: str):
        for stored_key, data, _content_type in self.uploads:
            if stored_key == key:
                return io.BytesIO(data)
        return io.BytesIO(self.blob)


class _FailureDB:
    """Independent session used to keep a failed export after the worker rolls back."""

    def __init__(self, questionnaire):
        self.questionnaire = questionnaire
        self.added: list = []
        self.committed = False

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "Questionnaire":
            return _Query(self.questionnaire)
        if name == "ExportRecord":
            records = [obj for obj in self.added if type(obj).__name__ == "ExportRecord"]
            return _Query(records[-1] if records else None)
        return _Query(None)

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def _questionnaire(filename: str):
    return SimpleNamespace(
        id=3,
        workspace_id=1,
        storage_key="raw/1/customer.bin",
        filename=filename,
    )


def _prepare(monkeypatch, blob: bytes, *, filename: str, fmt: str, questions=None, answers=None):
    from app import worker

    store = _Store(blob)
    questionnaire = _questionnaire(filename)
    failure_db = _FailureDB(questionnaire)
    monkeypatch.setattr(worker, "StorageClient", lambda: store)
    monkeypatch.setattr(worker, "_record_usage_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.storage_reconcile.commit_or_discard_object",
        lambda *args, **kwargs: None,
    )
    database = __import__("app.core.database", fromlist=["database"])
    monkeypatch.setattr(database, "Session" + "Local", lambda: failure_db)
    from app.models import Answer, ExportRecord, Question, Questionnaire

    session = _Session(
        {
            Questionnaire: questionnaire,
            ExportRecord: None,
            Question: list(questions or []),
            Answer: list(answers or []),
        }
    )
    job = SimpleNamespace(
        id=7,
        workspace_id=1,
        kind="export",
        lease_owner=None,
        result=None,
        attempt=1,
        status="running",
    )
    payload = {"questionnaire_id": 3, "workspace_id": 1, "format": fmt}
    return worker, job, session, store, failure_db, payload


def _failed_record(failure_db: _FailureDB):
    records = [obj for obj in failure_db.added if type(obj).__name__ == "ExportRecord"]
    assert records, "export failure did not write a failed export record"
    assert failure_db.committed is True
    return records[-1]


def _assert_no_substitute(store: _Store) -> None:
    for key, body, _content_type in store.uploads:
        assert not key.endswith(".docx")
        assert b"word/" not in body
        assert not key.endswith(".csv")
        assert _PRIVATE.encode() not in body


def _assert_fixed(exc, code: str, message: str) -> None:
    from app.core.job_errors import TerminalJobError

    assert isinstance(exc, TerminalJobError)
    assert exc.code == code
    assert str(exc) == message
    assert exc.message == message
    assert _PRIVATE not in str(exc)
    assert _PRIVATE not in exc.message


@pytest.mark.parametrize(
    "filename", ["customer.docx", "customer.doc", "customer.pdf", "customer.xls"]
)
def test_xlsx_request_does_not_substitute_another_format(monkeypatch, filename: str) -> None:
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch, b"not-a-workbook", filename=filename, fmt="xlsx"
    )
    with pytest.raises(Exception) as caught:
        worker.run_export(job, session, payload)
    _assert_fixed(caught.value, XLSX_FAILED, XLSX_FAILED_MESSAGE)
    _assert_no_substitute(store)
    record = _failed_record(failure_db)
    assert record.status == "failed"
    assert record.filename.endswith(".xlsx")
    assert not str(record.filename).endswith(".docx")
    assert str(record.storage_key).endswith(".failed")
    assert _PRIVATE not in str(record.filename)
    assert _PRIVATE not in str(record.storage_key)


def test_corrupt_xlsx_is_a_failed_export_not_a_docx(monkeypatch) -> None:
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch, b"this is not a workbook", filename="customer.xlsx", fmt="xlsx"
    )
    with pytest.raises(Exception) as caught:
        worker.run_export(job, session, payload)
    _assert_fixed(caught.value, XLSX_FAILED, XLSX_FAILED_MESSAGE)
    _assert_no_substitute(store)
    record = _failed_record(failure_db)
    assert record.status == "failed"
    assert record.filename == "customer.xlsx"
    assert record.job_id == job.id
    assert record.workspace_id == 1


def test_writer_exception_does_not_leak_or_substitute_docx(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError(_PRIVATE)

    monkeypatch.setattr("app.services.xlsx_writer.create_export_from_questionnaire", boom)
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch, _xlsx_bytes(), filename="customer.xlsx", fmt="xlsx"
    )
    calls: list[str] = []
    import app.services.fallback_export as fallback

    real = fallback.create_fallback_pack_docx

    def wrapped(*args, **kwargs):
        calls.append("docx")
        return real(*args, **kwargs)

    monkeypatch.setattr(fallback, "create_fallback_pack_docx", wrapped)
    with pytest.raises(Exception) as caught:
        worker.run_export(job, session, payload)
    _assert_fixed(caught.value, XLSX_FAILED, XLSX_FAILED_MESSAGE)
    assert calls == []
    _assert_no_substitute(store)
    record = _failed_record(failure_db)
    blob = " ".join(
        str(getattr(record, name, ""))
        for name in ("filename", "storage_key", "status", "error", "error_code")
    )
    assert _PRIVATE not in blob
    assert "secret-bucket" not in blob
    assert record.status == "failed"


def test_storage_failure_is_a_fixed_code_without_a_substitute(monkeypatch) -> None:
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch, _xlsx_bytes(), filename="customer.xlsx", fmt="xlsx"
    )

    def explode(*args, **kwargs):
        raise RuntimeError(_PRIVATE)

    store.upload = explode
    with pytest.raises(Exception) as caught:
        worker.run_export(job, session, payload)
    _assert_fixed(caught.value, STORAGE_FAILED, STORAGE_FAILED_MESSAGE)
    assert store.uploads == []
    record = _failed_record(failure_db)
    assert record.status == "failed"
    assert record.filename.endswith(".xlsx")
    assert _PRIVATE not in str(record.storage_key)
    assert "secret-bucket" not in str(record.filename)


def test_missing_docx_library_does_not_return_csv(monkeypatch) -> None:
    import sys

    import app.services.fallback_export as fallback

    monkeypatch.setitem(sys.modules, "docx", None)
    with pytest.raises(Exception) as caught:
        fallback.create_fallback_pack_docx([{"id": 1, "text": "Question"}], {1: "Answer"})
    assert "Question,Answer" not in str(caught.value)


def test_explicit_docx_request_keeps_docx_type_name_and_hash(monkeypatch) -> None:
    worker, job, session, store, _failure_db, payload = _prepare(
        monkeypatch, _xlsx_bytes(), filename="customer.xlsx", fmt="docx"
    )
    worker.run_export(job, session, payload)
    assert len(store.uploads) == 1
    key, body, content_type = store.uploads[0]
    assert key.endswith(".docx")
    assert body.startswith(b"PK")
    assert b"word/" in body
    assert content_type == DOCX_MEDIA
    recorded = json.loads(job.result)
    assert recorded["sha256"] == _sha256(body)
    assert recorded["content_type"] == DOCX_MEDIA
    assert recorded["filename"].endswith(".docx")
    completed = [obj for obj in session.added if type(obj).__name__ == "ExportRecord"]
    assert completed and completed[-1].status == "completed"
    assert completed[-1].filename.endswith(".docx")


def test_successful_xlsx_records_type_name_and_hash(monkeypatch) -> None:
    blob = _xlsx_bytes()
    worker, job, session, store, _failure_db, payload = _prepare(
        monkeypatch, blob, filename="customer.xlsx", fmt="xlsx"
    )
    worker.run_export(job, session, payload)
    assert len(store.uploads) == 1
    key, body, content_type = store.uploads[0]
    assert key.endswith(".xlsx")
    assert not key.endswith(".docx")
    assert b"word/" not in body
    assert b"xl/workbook.xml" in body.lower() or b"xl/workbook.xml" in body
    assert content_type == XLSX_MEDIA
    recorded = json.loads(job.result)
    assert recorded["sha256"] == _sha256(body)
    assert recorded["content_type"] == XLSX_MEDIA
    assert recorded["filename"] == "customer.xlsx"
    completed = [obj for obj in session.added if type(obj).__name__ == "ExportRecord"]
    assert len(completed) == 1
    assert completed[0].status == "completed"
    assert completed[0].filename == "customer.xlsx"
    assert completed[0].content_sha256 == _sha256(body)
    assert completed[0].object_version == 1
    assert completed[0].content_type == XLSX_MEDIA


class _RouteDB:
    def __init__(self, record, job):
        self.record = record
        self.job = job

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "ExportRecord":
            return _Query(self.record if isinstance(self.record, list) else [self.record])
        if name == "Job":
            return _Query([self.job] if self.job is not None else [])
        return _Query([])


def _route_record(**overrides):
    data = {
        "id": 11,
        "workspace_id": 1,
        "questionnaire_id": 3,
        "storage_key": "exports/1/job-7.xlsx",
        "filename": "customer.xlsx",
        "status": "completed",
        "job_id": 7,
        "created_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _route_job(result: dict | None, *, code: str | None = None, error: str | None = None):
    return SimpleNamespace(
        id=7,
        workspace_id=1,
        kind="export",
        status="failed" if code else "completed",
        error_code=code,
        error=error,
        result=json.dumps(result) if result is not None else None,
    )


class _DownloadStore:
    def __init__(self, body: bytes):
        self.body = body
        self.bucket_exports = "exports"

    def exists(self, bucket: str, key: str) -> bool:
        return True

    def download(self, bucket: str, key: str) -> bytes:
        return self.body

    def download_stream(self, bucket: str, key: str):
        return io.BytesIO(self.body)


def test_download_serves_recorded_hash_type_and_name() -> None:
    from app.api.routes.exports import get_download_url

    body = _xlsx_bytes()
    digest = _sha256(body)
    record = _route_record(content_sha256=digest, object_version=1, content_type=XLSX_MEDIA)
    job = _route_job({"sha256": digest, "content_type": XLSX_MEDIA, "filename": "customer.xlsx"})
    response = get_download_url(
        record_id=record.id,
        workspace_id=1,
        session={"workspace_id": 1, "email": "reviewer@example.com"},
        db=_RouteDB(record, job),
        storage=_DownloadStore(body),
    )
    assert response.status_code == 200
    assert response.media_type == XLSX_MEDIA
    disposition = response.headers["content-disposition"]
    assert "customer.xlsx" in disposition
    assert ".docx" not in disposition.lower()
    assert response.headers[SHA256_HEADER] == digest
    assert response.headers[SHA256_HEADER] == _sha256(body)


def test_download_of_failed_export_is_not_a_file() -> None:
    from app.api.routes.exports import get_download_url

    record = _route_record(
        status="failed", filename="customer.xlsx", storage_key="exports/1/job-7.failed"
    )
    job = _route_job(None, code=XLSX_FAILED, error=_PRIVATE)
    response = get_download_url(
        record_id=record.id,
        workspace_id=1,
        session={"workspace_id": 1, "email": "reviewer@example.com"},
        db=_RouteDB(record, job),
        storage=_DownloadStore(b"PK\x03\x04 word/ substitute"),
    )
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["error"]["code"] == XLSX_FAILED
    assert payload["error"]["message"] == XLSX_FAILED_MESSAGE
    assert _PRIVATE not in response.body.decode()
    assert b"word/" not in response.body


def test_download_rejects_a_hash_mismatch() -> None:
    from app.api.routes.exports import get_download_url

    body = _xlsx_bytes()
    record = _route_record(content_sha256="ab" * 32, object_version=1, content_type=XLSX_MEDIA)
    job = _route_job({"sha256": "ab" * 32, "content_type": XLSX_MEDIA, "filename": "customer.xlsx"})
    response = get_download_url(
        record_id=record.id,
        workspace_id=1,
        session={"workspace_id": 1, "email": "reviewer@example.com"},
        db=_RouteDB(record, job),
        storage=_DownloadStore(body),
    )
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["error"]["code"] == STORAGE_FAILED
    assert payload["error"]["message"] == STORAGE_FAILED_MESSAGE
    assert _sha256(body) not in response.body.decode()
    assert b"xl/" not in response.body


def test_list_exposes_failed_export_without_leaking() -> None:
    from app.api.routes.exports import list_export_records

    record = _route_record(status="failed", filename="customer.xlsx")
    job = _route_job(None, code=XLSX_FAILED, error=_PRIVATE)
    rows = list_export_records(
        workspace_id=1,
        session={"workspace_id": 1, "email": "reviewer@example.com"},
        db=_RouteDB(record, job),
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["filename"].endswith(".xlsx")
    assert rows[0]["error_code"] == XLSX_FAILED
    assert rows[0]["error"] == XLSX_FAILED_MESSAGE
    assert rows[0]["sha256"] is None
    assert _PRIVATE not in json.dumps(rows)


def test_list_includes_recorded_sha256_for_a_completed_export() -> None:
    from app.api.routes.exports import list_export_records

    digest = _sha256(b"synthetic-export-bytes")
    record = _route_record(status="completed", filename="customer.docx")
    job = _route_job({"sha256": digest, "content_type": DOCX_MEDIA, "filename": "customer.docx"})
    job.status = "completed"
    job.error_code = None
    job.error = None
    rows = list_export_records(
        workspace_id=1,
        session={"workspace_id": 1, "email": "reviewer@example.com"},
        db=_RouteDB(record, job),
    )
    assert rows[0]["status"] == "completed"
    assert rows[0]["sha256"] == digest
    assert rows[0]["content_type"] == DOCX_MEDIA
    assert rows[0]["error_code"] is None
    assert rows[0]["filename"].endswith(".docx")


def test_explicit_docx_failure_does_not_change_format(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError(_PRIVATE)

    monkeypatch.setattr("app.services.fallback_export.create_fallback_pack_docx", boom)
    monkeypatch.setattr("app.services.docx_writer.create_export_from_questionnaire_docx", boom)
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch, _xlsx_bytes(), filename="customer.xlsx", fmt="docx"
    )
    with pytest.raises(Exception) as caught:
        worker.run_export(job, session, payload)
    _assert_fixed(caught.value, DOCX_FAILED, DOCX_FAILED_MESSAGE)
    _assert_no_substitute(store)
    record = _failed_record(failure_db)
    assert record.status == "failed"
    assert record.filename.endswith(".docx")
    assert _PRIVATE not in str(record.filename)


def _mapped_workbook(question_text: str = _MAPPED_QUESTION) -> bytes:
    """Question in A, owner in B, answer in C. Offset placement would hit the owner."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Security"
    ws["A1"] = "Question"
    ws["B1"] = "Owner"
    ws["C1"] = "Answer"
    ws["A2"] = question_text
    ws["B2"] = "Alice"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _mapped_question(
    blob: bytes, *, file_digest: str | None = None, stored_text: str | None = None
):
    from app.services.cell_mapping import content_hash, file_hash
    from app.services.question_normalizer import normalize_question

    text = stored_text or _MAPPED_QUESTION
    return SimpleNamespace(
        id=1,
        text=text,
        source_location=json.dumps({"sheet": "Security", "row": 2, "col": 1}),
        content_hash=content_hash(normalize_question(text)),
        original_file_hash=file_hash(blob) if file_digest is None else file_digest,
        sheet="Security",
        question_cell="A2",
        answer_cell="C2",
        mapping_version=1,
    )


def _mapped_answer():
    return SimpleNamespace(question_id=1, text=_MAPPED_ANSWER, status="approved")


def _cell(blob: bytes, coordinate: str) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(blob))
    value = wb["Security"][coordinate].value
    return "" if value is None else str(value)


def _assert_mapping_conflict(caught, failure_db, store: _Store) -> None:
    _assert_fixed(caught.value, MAPPING_STALE, MAPPING_STALE_MESSAGE)
    assert _MAPPED_QUESTION not in str(caught.value)
    assert "PRIVATE-ANSWER" not in str(caught.value)
    assert store.uploads == []
    record = _failed_record(failure_db)
    assert record.status == "failed"
    assert record.filename.endswith(".xlsx")
    assert "PRIVATE-ANSWER" not in str(record.filename)
    assert "PRIVATE-ANSWER" not in str(record.storage_key)


def test_stale_workbook_fingerprint_does_not_write_answers(monkeypatch) -> None:
    blob = _mapped_workbook()
    question = _mapped_question(blob, file_digest="ab" * 32)
    worker, _job, session, store, failure_db, payload = _prepare(
        monkeypatch,
        blob,
        filename="customer.xlsx",
        fmt="xlsx",
        questions=[question],
        answers=[_mapped_answer()],
    )
    with pytest.raises(Exception) as caught:
        worker.run_export(_job, session, payload)
    _assert_mapping_conflict(caught, failure_db, store)


def test_stale_question_cell_does_not_write_answers(monkeypatch) -> None:
    blob = _mapped_workbook("Where is the office located today?")
    question = _mapped_question(blob, stored_text=_MAPPED_QUESTION)
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch,
        blob,
        filename="customer.xlsx",
        fmt="xlsx",
        questions=[question],
        answers=[_mapped_answer()],
    )
    with pytest.raises(Exception) as caught:
        worker.run_export(job, session, payload)
    _assert_mapping_conflict(caught, failure_db, store)


def test_current_mapping_writes_the_answer_cell_not_the_neighbor(monkeypatch) -> None:
    blob = _mapped_workbook()
    question = _mapped_question(blob)
    worker, job, session, store, _failure_db, payload = _prepare(
        monkeypatch,
        blob,
        filename="customer.xlsx",
        fmt="xlsx",
        questions=[question],
        answers=[_mapped_answer()],
    )
    worker.run_export(job, session, payload)
    assert len(store.uploads) == 1
    _key, body, content_type = store.uploads[0]
    assert content_type == XLSX_MEDIA
    assert _cell(body, "C2") == _MAPPED_ANSWER
    assert _cell(body, "B2") == "Alice"
    assert _MAPPED_ANSWER not in _cell(body, "B2")


class EndpointConnectionError(Exception):
    """Shape-compatible with botocore's connection error. Classification is by class name."""


class ReadTimeoutError(Exception):
    """Shape-compatible with urllib3's read timeout. Classification is by class name."""


class ClientError(Exception):
    """Shape-compatible with botocore ClientError. The body is not a safe message."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__(f"An error occurred ({code}) PRIVATE storage body")
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


def _flaky_upload(store: _Store, exc: BaseException):
    calls = {"n": 0}

    def upload(bucket: str, key: str, body, content_type: str | None = None) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise exc
        data = body.read() if hasattr(body, "read") else body
        store.uploads.append((key, bytes(data), content_type))
        return key

    store.upload = upload
    return calls


@pytest.mark.parametrize(
    "exc",
    [
        EndpointConnectionError("PRIVATE endpoint"),
        ReadTimeoutError("PRIVATE timeout"),
        ClientError("ServiceUnavailable", 503),
        ClientError("InternalError", 500),
        ClientError("Throttling", 400),
        ClientError("SlowDown", 503),
    ],
)
def test_transient_storage_error_retries_then_completes(monkeypatch, exc: Exception) -> None:
    from app.core.job_errors import classify, is_retryable_code

    blob = _xlsx_bytes()
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch, blob, filename="customer.xlsx", fmt="xlsx"
    )
    job.attempt = 1
    job.max_attempts = 3
    _flaky_upload(store, exc)
    with pytest.raises(type(exc)) as caught:
        worker.run_export(job, session, payload)
    assert is_retryable_code(classify(caught.value)) is True
    assert "PRIVATE" not in failure_db.added.__repr__()
    assert failure_db.added == []
    assert failure_db.committed is False
    job.attempt = 2
    worker.run_export(job, session, payload)
    assert len(store.uploads) == 1
    assert store.uploads[0][0].endswith(".xlsx")
    completed = [obj for obj in session.added if type(obj).__name__ == "ExportRecord"]
    assert completed and completed[-1].status == "completed"
    assert failure_db.added == []


def test_permanent_storage_error_fails_on_the_first_attempt(monkeypatch) -> None:
    blob = _xlsx_bytes()
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch, blob, filename="customer.xlsx", fmt="xlsx"
    )
    job.attempt = 1
    job.max_attempts = 3

    def explode(*args, **kwargs):
        raise ClientError("AccessDenied", 403)

    store.upload = explode
    with pytest.raises(Exception) as caught:
        worker.run_export(job, session, payload)
    _assert_fixed(caught.value, STORAGE_FAILED, STORAGE_FAILED_MESSAGE)
    assert "PRIVATE" not in str(caught.value)
    assert "AccessDenied" not in str(caught.value)
    assert store.uploads == []
    record = _failed_record(failure_db)
    assert record.status == "failed"
    assert record.filename.endswith(".xlsx")


def test_persistent_storage_error_fails_on_the_last_attempt(monkeypatch) -> None:
    blob = _xlsx_bytes()
    worker, job, session, store, failure_db, payload = _prepare(
        monkeypatch, blob, filename="customer.xlsx", fmt="xlsx"
    )
    job.attempt = 3
    job.max_attempts = 3

    def explode(*args, **kwargs):
        raise ClientError("ServiceUnavailable", 503)

    store.upload = explode
    with pytest.raises(Exception) as caught:
        worker.run_export(job, session, payload)
    _assert_fixed(caught.value, STORAGE_FAILED, STORAGE_FAILED_MESSAGE)
    assert "PRIVATE" not in str(caught.value)
    assert store.uploads == []
    record = _failed_record(failure_db)
    assert record.status == "failed"
    assert record.filename.endswith(".xlsx")


def test_download_of_stale_mapping_is_the_mapping_conflict() -> None:
    from app.api.routes.exports import get_download_url

    record = _route_record(
        status="failed", filename="customer.xlsx", storage_key="exports/1/job-7.failed"
    )
    job = _route_job(None, code=MAPPING_STALE, error=_PRIVATE + " " + _MAPPED_QUESTION)
    response = get_download_url(
        record_id=record.id,
        workspace_id=1,
        session={"workspace_id": 1, "email": "reviewer@example.com"},
        db=_RouteDB(record, job),
        storage=_DownloadStore(b"PK\x03\x04 wrong-cell"),
    )
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["error"]["code"] == MAPPING_STALE
    assert payload["error"]["message"] == MAPPING_STALE_MESSAGE
    assert _PRIVATE not in response.body.decode()
    assert _MAPPED_QUESTION not in response.body.decode()
    assert b"wrong-cell" not in response.body
