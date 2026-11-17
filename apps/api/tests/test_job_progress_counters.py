"""TC-15-038c: parse, evidence parse, index and export record a generated/total pair.

The numbers are the work the worker actually did. A kind that records no pair stays
without one, and the history projection does not invent counters for it.
"""

import io
import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

pytestmark = pytest.mark.unit

_EMB = [0.01] * 1536


class _Query:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, *args, **kwargs):
        return self

    def populate_existing(self):
        return self

    def with_for_update(self):
        return self

    def join(self, *args, **kwargs):
        return self

    def delete(self):
        name = getattr(self.model, "__name__", "")
        if name == "Chunk":
            self.session.chunks.clear()
        return 0

    def first(self):
        name = getattr(self.model, "__name__", "")
        if name == "Questionnaire":
            return self.session.questionnaire
        if name == "Document":
            return self.session.document
        if name == "ExportRecord":
            return self.session.export_record
        return None

    def all(self):
        name = getattr(self.model, "__name__", "")
        if name == "Chunk":
            return list(self.session.chunks)
        if name == "Question":
            return list(self.session.questions)
        if name == "Answer":
            return list(self.session.answers)
        return []

    def count(self):
        name = getattr(self.model, "__name__", "")
        if name == "Question":
            return len(self.session.questions)
        if name == "Chunk":
            return len(self.session.chunks)
        return 0


class _Session:
    def __init__(self):
        self.questionnaire = None
        self.document = None
        self.export_record = None
        self.questions: list = []
        self.answers: list = []
        self.chunks: list = []
        self.added: list = []

    def query(self, model):
        return _Query(self, model)

    def add(self, obj):
        self.added.append(obj)
        name = type(obj).__name__
        if name == "Chunk":
            obj.id = len(self.chunks) + 1
            self.chunks.append(obj)
        if name == "Question":
            self.questions.append(obj)

    def flush(self):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 11

    def execute(self, *args, **kwargs):
        return None

    def get_bind(self):
        return self


class _Effects:
    def __init__(self, session, job):
        self.session = session
        self.job = job

    def is_applied(self, effect):
        return False

    def mark_applied(self, effect, detail=None):
        return None

    def provider_call_started(self, provider):
        return None

    def settle(self, provider, detail=None):
        return None


class _Store:
    def __init__(self, blob: bytes):
        self.blob = blob
        self.bucket_raw = "raw"
        self.bucket_exports = "exports"
        self.uploads: list = []

    def download(self, bucket, key):
        return self.blob

    def upload(self, bucket, key, body, content_type=None):
        data = body.read() if hasattr(body, "read") else body
        self.uploads.append((key, bytes(data), content_type))
        return key


def _pair(job) -> dict:
    assert job.result, "worker recorded no result"
    data = json.loads(job.result)
    assert type(data["generated"]) is int
    assert type(data["total"]) is int
    assert 0 <= data["generated"] <= data["total"]
    return data


def _job(kind, **extra):
    base = dict(
        id=7,
        workspace_id=1,
        kind=kind,
        status="running",
        attempt=1,
        max_attempts=3,
        result=None,
        payload="{}",
        error_code=None,
        lease_owner=None,
        input_version=None,
        next_attempt_at=None,
        created_at=None,
        started_at=None,
        completed_at=None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _patch_storage(monkeypatch, worker, blob: bytes) -> _Store:
    store = _Store(blob)
    monkeypatch.setattr(worker, "StorageClient", lambda: store)
    monkeypatch.setattr(worker, "JobEffects", _Effects)
    return store


def test_parse_questionnaire_records_saved_question_counts(monkeypatch):
    from app import worker

    questions = [{"text": "Do you encrypt data?"}, {"text": "Who reviews access?"}]
    session = _Session()
    session.questionnaire = SimpleNamespace(
        id=3,
        workspace_id=1,
        filename="questions.xlsx",
        storage_key="raw/1/questions.xlsx",
        status="uploaded",
        deleted_at=None,
        parse_metadata=None,
    )
    _patch_storage(monkeypatch, worker, b"workbook")
    monkeypatch.setattr(worker, "parse_xlsx_questionnaire", lambda path: list(questions))
    monkeypatch.setattr(worker, "_auto_classify_questionnaire", lambda *args, **kwargs: None)
    job = _job("parse_questionnaire")
    worker.run_parse_questionnaire(
        job,
        session,
        {"questionnaire_id": 3, "storage_key": "raw/1/questions.xlsx"},
    )
    data = _pair(job)
    saved = [obj for obj in session.added if type(obj).__name__ == "Question"]
    assert data["generated"] == len(saved) == len(questions)
    assert data["total"] == len(questions)


def test_parse_evidence_stays_a_noop(monkeypatch):
    from app import worker

    opened = {"n": 0}

    def _storage():
        opened["n"] += 1
        raise AssertionError("parse_evidence must not touch storage")

    monkeypatch.setattr(worker, "StorageClient", _storage)
    job = _job("parse_evidence", payload=json.dumps({"document_id": 8}))
    worker.run_job(job, _Session())
    assert job.result is None
    assert opened["n"] == 0


def test_publish_without_a_lease_owner_does_not_open_a_session():
    from app import worker

    def factory():
        raise AssertionError("no session without an owner")

    assert worker.publish_running_progress(7, None, 1, 3, session_factory=factory) is False


def test_index_document_records_embedded_and_chunk_counts(monkeypatch):
    from app import worker
    from app.services import index_service

    session = _Session()
    session.document = SimpleNamespace(
        id=8,
        workspace_id=1,
        filename="policy.txt",
        storage_key="raw/1/policy.txt",
        status="uploaded",
        deleted_at=None,
        index_error=None,
    )
    _patch_storage(monkeypatch, worker, b"policy text")
    chunks = [
        {"text": "a", "metadata": {}},
        {"text": "b", "metadata": {}},
        {"text": "c", "metadata": {}},
    ]
    monkeypatch.setattr(index_service, "parse_evidence", lambda path: [{"text": "policy"}])
    monkeypatch.setattr(index_service, "chunk_evidence", lambda parsed: list(chunks))
    monkeypatch.setattr(
        index_service,
        "embed_texts",
        lambda texts: [_EMB, None, _EMB],
    )
    monkeypatch.setattr(
        "app.services.tag_service.auto_tag_document",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        "app.core.corpus_version.bump_corpus_version",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.retrieval_cache.invalidate_workspace",
        lambda *args, **kwargs: None,
    )
    job = _job("index_document")
    worker.run_index_document(job, session, {"document_id": 8})
    data = _pair(job)
    assert data["total"] == len(chunks)
    assert data["generated"] == 2


def test_export_records_question_counts(monkeypatch):
    from app import worker

    book = Workbook()
    book.active.title = "Security"
    book.active["A1"] = "Question"
    buf = io.BytesIO()
    book.save(buf)
    session = _Session()
    session.questionnaire = SimpleNamespace(
        id=3,
        workspace_id=1,
        filename="customer.xlsx",
        storage_key="raw/1/customer.xlsx",
        status="parsed",
        deleted_at=None,
    )
    session.questions = [
        SimpleNamespace(
            id=1,
            text="Do you encrypt data?",
            source_location=None,
            content_hash=None,
            original_file_hash=None,
            sheet=None,
            question_cell=None,
            answer_cell=None,
            mapping_version=0,
        ),
        SimpleNamespace(
            id=2,
            text="Who reviews access?",
            source_location=None,
            content_hash=None,
            original_file_hash=None,
            sheet=None,
            question_cell=None,
            answer_cell=None,
            mapping_version=0,
        ),
    ]
    _patch_storage(monkeypatch, worker, buf.getvalue())
    monkeypatch.setattr(worker, "_record_usage_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.storage_reconcile.commit_or_discard_object",
        lambda *args, **kwargs: None,
    )
    job = _job("export")
    worker.run_export(
        job,
        session,
        {"questionnaire_id": 3, "workspace_id": 1, "format": "xlsx"},
    )
    data = _pair(job)
    assert data["generated"] == len(session.questions)
    assert data["total"] == len(session.questions)
    assert data["export_record_id"] == 11
    assert "storage_key" in data


def test_history_projects_pairs_for_workers_that_record_them(monkeypatch):
    from app.api.routes import jobs as routes

    monkeypatch.setattr(routes, "charge_uncertain", lambda db, job_id: False)
    request = SimpleNamespace()
    for kind, generated, total in (
        ("parse_questionnaire", 2, 2),
        ("parse_evidence", 4, 4),
        ("index_document", 2, 3),
        ("export", 5, 5),
        ("generate_answers", 2, 5),
    ):
        job = _job(
            kind,
            result=json.dumps({"generated": generated, "total": total, "storage_key": "PRIVATE"}),
        )
        item = routes._history_job(request, None, job)
        assert item["progress"] == {"generated": generated, "total": total}
        assert "PRIVATE" not in json.dumps(item["progress"])

    silent = _job("export", result="{}")
    assert routes._history_job(request, None, silent)["progress"] is None
    unknown = _job("sync", result=json.dumps({"generated": 1, "total": 1}))
    assert routes._history_job(request, None, unknown)["progress"] is None


def test_export_detail_keeps_the_pair_and_drops_other_result_fields():
    from app.api.routes import jobs as routes

    record = SimpleNamespace(id=9, storage_key="exports/1/job-7.xlsx")

    class _Rows:
        def join(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return record

    job = _job(
        "export",
        payload=json.dumps({"workspace_id": 1, "questionnaire_id": 3}),
        result=json.dumps(
            {
                "export_record_id": 9,
                "storage_key": "PRIVATE-forged",
                "download_url": "PRIVATE-url",
                "generated": 2,
                "total": 4,
            }
        ),
    )
    projected = routes._export_artifact_result(SimpleNamespace(query=lambda model: _Rows()), job)
    assert projected == {
        "export_record_id": 9,
        "storage_key": "exports/1/job-7.xlsx",
        "generated": 2,
        "total": 4,
    }
