"""TC-10-005: a stored object and its database row stay consistent.

Two failure cases are covered. The object can be stored and the commit can still fail. The row can
be committed and the job can still be missing. Orphans are removed only when nothing references
them and they are strictly older than the grace period. A dry-run deletes nothing.

Fakes only: an in-memory store, the side ``*_test`` database, no network, no real keys. The
fixture records max(id) and counts, deletes rows above that id, and asserts the counts. It does
not call setval. Storage objects are cleared with the fake.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.core.database import SessionLocal
from app.models import (
    Document,
    EvidenceVersion,
    ExportRecord,
    Job,
    JobStatus,
    Questionnaire,
    TrustRequest,
)
from app.models.evidence_item import EvidenceItem
from app.services.storage_reconcile import (
    commit_or_discard_object,
    discard_if_unreferenced,
    execute_cli,
    orphan_grace_seconds,
    reconcile_missing_jobs,
    reconcile_orphan_objects,
    sweep_orphans_best_effort,
)

WS = 1
OTHER = 2
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
GRACE = 100

TABLES = (
    "documents",
    "questionnaires",
    "jobs",
    "export_records",
    "trust_requests",
    "job_effects",
    "evidence_items",
    "evidence_versions",
    "audit_events",
    "user_sessions",
)
DELETE_ORDER = (
    "job_effects",
    "export_records",
    "evidence_versions",
    "evidence_items",
    "jobs",
    "documents",
    "questionnaires",
    "trust_requests",
    "audit_events",
    "user_sessions",
)


class MemoryStorage:
    """In-memory object store. No network and no credentials."""

    def __init__(self) -> None:
        self.bucket_raw = "test-raw"
        self.bucket_exports = "test-exports"
        self.objects: dict[tuple[str, str], dict] = {}
        self.fail_delete: set[tuple[str, str]] = set()
        self.list_error: BaseException | None = None
        self.deletes: list[tuple[str, str]] = []

    def put(
        self,
        bucket: str,
        key: str,
        body: bytes = b"synthetic",
        *,
        when: datetime | None = None,
        age_seconds: int = 0,
    ):
        moment = when or (datetime.now(timezone.utc) - timedelta(seconds=age_seconds))
        self.objects[(bucket, key)] = {"body": body, "last_modified": moment}
        return key

    def delete(self, bucket: str, key: str) -> None:
        self.deletes.append((bucket, key))
        if (bucket, key) in self.fail_delete:
            raise RuntimeError("synthetic delete failure")
        self.objects.pop((bucket, key), None)

    def list_objects(self, bucket: str) -> list[dict]:
        if self.list_error is not None:
            raise self.list_error
        return [
            {"key": key, "last_modified": meta["last_modified"]}
            for (found, key), meta in self.objects.items()
            if found == bucket
        ]

    def contains(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self.objects

    def clear(self) -> None:
        self.objects.clear()
        self.deletes.clear()
        self.fail_delete.clear()


@pytest.fixture
def db(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    session = SessionLocal()
    snap: dict[str, tuple[int, int]] = {}
    for table in TABLES:
        max_id, count = session.execute(
            text(f"SELECT COALESCE(MAX(id), 0), COUNT(*) FROM {table}")
        ).one()
        snap[table] = (int(max_id), int(count))
    session.commit()
    session.info["snap"] = snap
    try:
        yield session
    finally:
        try:
            session.rollback()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass
        cleanup = SessionLocal()
        try:
            for table in DELETE_ORDER:
                cleanup.execute(
                    text(f"DELETE FROM {table} WHERE id > :max_id"),
                    {"max_id": snap[table][0]},
                )
            cleanup.commit()
            for table in TABLES:
                got = cleanup.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                assert int(got) == snap[table][1], table
        finally:
            cleanup.close()


@pytest.fixture
def store():
    memory = MemoryStorage()
    try:
        yield memory
    finally:
        memory.clear()


def _mark(db, table: str) -> int:
    return int(db.info["snap"][table][0])


def _login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _post_upload(client: TestClient, url: str):
    return client.post(
        url,
        data={"workspace_id": str(WS)},
        files={"file": ("synthetic.txt", b"synthetic enqueue consistency text", "text/plain")},
    )


def _patch_route_storage(monkeypatch, memory: MemoryStorage, *, fail_delete: bool) -> None:
    def upload(self, bucket, key, body, content_type=None):
        content = body.read() if hasattr(body, "read") else body
        memory.put(bucket, key, content, when=NOW - timedelta(seconds=GRACE + 5))
        return key

    def delete(self, bucket, key):
        if fail_delete:
            memory.deletes.append((bucket, key))
            raise RuntimeError("synthetic delete failure")
        memory.delete(bucket, key)

    monkeypatch.setattr("app.services.storage.StorageClient.upload", upload)
    monkeypatch.setattr("app.services.storage.StorageClient.delete", delete)


def _rows_above(db, model, table: str):
    db.rollback()
    return db.query(model).filter(model.id > _mark(db, table)).all()


def _jobs_for(db, kind: str, field: str, resource_id: int) -> list[Job]:
    db.rollback()
    found = []
    for job in db.query(Job).filter(Job.kind == kind, Job.id > _mark(db, "jobs")).all():
        try:
            payload = json.loads(job.payload or "{}")
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get(field) == resource_id:
            found.append(job)
    return found


def _sweep(db, memory: MemoryStorage, **kwargs):
    kwargs.setdefault("grace_seconds", GRACE)
    kwargs.setdefault("now", NOW)
    return reconcile_orphan_objects(db, memory, **kwargs)


# --------------------------------------------------------------------------------------------------
# AC1a: object stored, database commit fails
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,model,table",
    [
        ("/api/documents/upload", Document, "documents"),
        ("/api/questionnaires/upload", Questionnaire, "questionnaires"),
    ],
)
def test_storage_put_ok_db_commit_raises_removes_the_object_and_the_row(
    client: TestClient, db, store: MemoryStorage, monkeypatch, url, model, table
):
    _login(client, "admin@trust.local", "a")
    _patch_route_storage(monkeypatch, store, fail_delete=False)

    def fail(self):
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(OrmSession, "commit", fail)
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        _post_upload(client, url)
    assert store.objects == {}
    assert _rows_above(db, model, table) == []
    assert _rows_above(db, Job, "jobs") == []


@pytest.mark.parametrize(
    "url,model,table",
    [
        ("/api/documents/upload", Document, "documents"),
        ("/api/questionnaires/upload", Questionnaire, "questionnaires"),
    ],
)
def test_commit_failure_with_a_failed_delete_is_reconciled_by_the_sweep(
    client: TestClient, db, store: MemoryStorage, monkeypatch, url, model, table
):
    _login(client, "admin@trust.local", "a")
    _patch_route_storage(monkeypatch, store, fail_delete=True)

    def fail(self):
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(OrmSession, "commit", fail)
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        _post_upload(client, url)
    assert len(store.objects) == 1
    assert _rows_above(db, model, table) == []
    # The immediate delete failed. The object is already older than the grace period.
    dry = _sweep(db, store, dry_run=True)
    assert len(dry.candidates) == 1
    assert store.objects
    done = _sweep(db, store, dry_run=False)
    assert len(done.deleted) == 1
    assert store.objects == {}
    again = _sweep(db, store, dry_run=False)
    assert again.candidates == () and again.deleted == ()


def test_commit_failure_does_not_delete_a_key_a_row_already_references(
    client: TestClient, db, store: MemoryStorage, monkeypatch
):
    key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    original = b"original bytes that must survive"
    store.put(store.bucket_raw, key, original, when=NOW - timedelta(seconds=GRACE + 5))
    db.add(
        Document(
            workspace_id=WS,
            storage_key=key,
            filename="kept.txt",
            status="indexed",
        )
    )
    db.commit()
    _login(client, "admin@trust.local", "a")

    def upload(self, bucket, key_arg, body, content_type=None):
        content = body.read() if hasattr(body, "read") else body
        store.put(bucket, key_arg, content, when=NOW)
        return key_arg

    monkeypatch.setattr("app.services.storage.StorageClient.upload", upload)
    monkeypatch.setattr("app.services.storage.StorageClient.delete", store.delete)
    monkeypatch.setattr("app.services.file_service.make_key", lambda *a, **k: key)

    def fail(self):
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(OrmSession, "commit", fail)
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        _post_upload(client, "/api/documents/upload")
    assert store.contains(store.bucket_raw, key)
    assert _rows_above(db, Document, "documents")
    kept = [row for row in _rows_above(db, Document, "documents") if row.storage_key == key]
    assert len(kept) == 1
    result = _sweep(db, store, dry_run=False)
    assert (store.bucket_raw, key) not in result.deleted
    assert store.contains(store.bucket_raw, key)


def test_export_commit_failure_discards_the_object_and_leaves_no_row(db, store: MemoryStorage):
    key = f"exports/{WS}/job-{uuid.uuid4().hex}.xlsx"
    store.put(store.bucket_exports, key, b"export-bytes", when=NOW)
    db.add(
        ExportRecord(
            workspace_id=WS,
            storage_key=key,
            filename="answers.xlsx",
            status="completed",
        )
    )

    def fail():
        raise RuntimeError("synthetic commit failure")

    db.commit = fail
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        commit_or_discard_object(db, store, store.bucket_exports, key)
    assert not store.contains(store.bucket_exports, key)
    assert _rows_above(db, ExportRecord, "export_records") == []


def test_export_commit_failure_keeps_an_object_another_row_references(db, store: MemoryStorage):
    key = f"exports/{WS}/job-{uuid.uuid4().hex}.xlsx"
    store.put(store.bucket_exports, key, b"live-export", when=NOW - timedelta(days=2))
    live = ExportRecord(
        workspace_id=WS,
        storage_key=key,
        filename="live.xlsx",
        status="completed",
    )
    db.add(live)
    db.commit()
    db.add(
        ExportRecord(
            workspace_id=WS,
            storage_key=key,
            filename="second.xlsx",
            status="completed",
        )
    )

    def fail():
        raise RuntimeError("synthetic commit failure")

    db.commit = fail
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        commit_or_discard_object(db, store, store.bucket_exports, key)
    assert store.contains(store.bucket_exports, key)
    db.rollback()
    rows = _rows_above(db, ExportRecord, "export_records")
    assert [row.filename for row in rows] == ["live.xlsx"]
    result = _sweep(db, store, dry_run=False)
    assert (store.bucket_exports, key) not in result.deleted


def test_export_delete_failure_is_left_for_the_sweep(db, store: MemoryStorage):
    key = f"exports/{WS}/job-{uuid.uuid4().hex}.xlsx"
    store.put(store.bucket_exports, key, b"export-bytes", when=NOW - timedelta(seconds=GRACE + 5))
    store.fail_delete.add((store.bucket_exports, key))
    db.add(
        ExportRecord(workspace_id=WS, storage_key=key, filename="answers.xlsx", status="completed")
    )

    def fail():
        raise RuntimeError("synthetic commit failure")

    db.commit = fail
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        commit_or_discard_object(db, store, store.bucket_exports, key)
    assert store.contains(store.bucket_exports, key)
    assert _rows_above(db, ExportRecord, "export_records") == []
    store.fail_delete.clear()
    done = _sweep(db, store, dry_run=False)
    assert (store.bucket_exports, key) in done.deleted
    assert not store.contains(store.bucket_exports, key)


# --------------------------------------------------------------------------------------------------
# AC1b: database commit succeeds, job enqueue fails
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,model,table,module",
    [
        ("/api/documents/upload", Document, "documents", "app.api.routes.documents"),
        (
            "/api/questionnaires/upload",
            Questionnaire,
            "questionnaires",
            "app.api.routes.questionnaires",
        ),
    ],
)
def test_enqueue_failure_rolls_back_the_row_and_removes_the_object(
    client: TestClient, db, store: MemoryStorage, monkeypatch, url, model, table, module
):
    _login(client, "admin@trust.local", "a")
    _patch_route_storage(monkeypatch, store, fail_delete=False)

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic enqueue failure")

    monkeypatch.setattr(f"{module}.enqueue_job", boom)
    with pytest.raises(RuntimeError, match="synthetic enqueue failure"):
        _post_upload(client, url)
    assert store.objects == {}
    assert _rows_above(db, model, table) == []
    assert _rows_above(db, Job, "jobs") == []


def test_committed_row_without_a_job_is_detected_and_reenqueued(db, store: MemoryStorage):
    doc_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    qnr_key = f"raw/{WS}/{uuid.uuid4().hex}.xlsx"
    doc = Document(workspace_id=WS, storage_key=doc_key, filename="late.txt", status="uploaded")
    qnr = Questionnaire(
        workspace_id=WS, storage_key=qnr_key, filename="late.xlsx", status="uploaded"
    )
    empty = Questionnaire(
        workspace_id=WS, storage_key=None, filename="no-file.xlsx", status="uploaded"
    )
    db.add_all([doc, qnr, empty])
    db.commit()
    store.put(store.bucket_raw, doc_key, when=NOW)
    store.put(store.bucket_raw, qnr_key, when=NOW)

    first = reconcile_missing_jobs(db)
    assert first["index_document"] >= 1
    assert first["parse_questionnaire"] >= 1
    doc_jobs = _jobs_for(db, "index_document", "document_id", doc.id)
    qnr_jobs = _jobs_for(db, "parse_questionnaire", "questionnaire_id", qnr.id)
    assert len(doc_jobs) == 1 and doc_jobs[0].status == JobStatus.QUEUED.value
    assert doc_jobs[0].input_version == doc_key
    assert len(qnr_jobs) == 1 and qnr_jobs[0].input_version == qnr_key
    assert _jobs_for(db, "parse_questionnaire", "questionnaire_id", empty.id) == []

    reconcile_missing_jobs(db)
    # Running it again does not create a second job for these rows.
    assert len(_jobs_for(db, "index_document", "document_id", doc.id)) == 1
    assert len(_jobs_for(db, "parse_questionnaire", "questionnaire_id", qnr.id)) == 1
    # The originals stay. Re-enqueue is not a delete.
    assert store.contains(store.bucket_raw, doc_key)
    assert store.contains(store.bucket_raw, qnr_key)


def test_reenqueue_failure_leaves_the_row_for_a_later_pass(db, monkeypatch):
    qnr = Questionnaire(
        workspace_id=WS,
        storage_key=f"raw/{WS}/{uuid.uuid4().hex}.xlsx",
        filename="retry.xlsx",
        status="uploaded",
    )
    db.add(qnr)
    db.commit()
    qnr_id = qnr.id

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic enqueue failure")

    monkeypatch.setattr("app.services.storage_reconcile.enqueue_job", boom)
    counts = reconcile_missing_jobs(db)
    assert counts["parse_questionnaire"] == 0
    db.rollback()
    assert db.get(Questionnaire, qnr_id).status == "uploaded"
    assert _jobs_for(db, "parse_questionnaire", "questionnaire_id", qnr_id) == []

    monkeypatch.undo()
    reconcile_missing_jobs(db)
    assert len(_jobs_for(db, "parse_questionnaire", "questionnaire_id", qnr_id)) == 1


# --------------------------------------------------------------------------------------------------
# Sweep: references, grace, idempotence, dry-run, isolation
# --------------------------------------------------------------------------------------------------


def test_sweep_never_deletes_a_referenced_original(db, store: MemoryStorage):
    old = NOW - timedelta(seconds=GRACE + 30)
    doc_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    archived_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    qnr_key = f"raw/{WS}/{uuid.uuid4().hex}.xlsx"
    export_key = f"exports/{WS}/job-{uuid.uuid4().hex}.xlsx"
    trust_key = f"trust-requests/{WS}/9/{uuid.uuid4().hex}.pdf"
    evidence_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    pinned_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    payload_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    finished_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    for bucket, key in (
        (store.bucket_raw, doc_key),
        (store.bucket_raw, archived_key),
        (store.bucket_raw, qnr_key),
        (store.bucket_exports, export_key),
        (store.bucket_raw, trust_key),
        (store.bucket_raw, evidence_key),
        (store.bucket_raw, pinned_key),
        (store.bucket_raw, payload_key),
        (store.bucket_raw, finished_key),
    ):
        store.put(bucket, key, when=old)

    doc = Document(workspace_id=WS, storage_key=doc_key, filename="live.txt", status="indexed")
    archived = Document(
        workspace_id=WS,
        storage_key=archived_key,
        filename="archived.txt",
        status="indexed",
        deleted_at=NOW,
    )
    qnr = Questionnaire(workspace_id=WS, storage_key=qnr_key, filename="live.xlsx", status="parsed")
    trust = TrustRequest(
        workspace_id=WS,
        requester_email="person@example.test",
        message="synthetic",
        attachment_storage_key=trust_key,
    )
    item = EvidenceItem(workspace_id=WS, title="synthetic evidence", source_type="manual")
    db.add_all([doc, archived, qnr, trust, item])
    db.flush()
    db.add(EvidenceVersion(evidence_id=item.id, version_number=1, content_ref=evidence_key))
    db.add(
        ExportRecord(
            workspace_id=WS, storage_key=export_key, filename="live.xlsx", status="completed"
        )
    )
    db.add(
        Job(
            workspace_id=WS,
            kind="index_document",
            status=JobStatus.QUEUED.value,
            payload="{}",
            input_version=pinned_key,
        )
    )
    db.add(
        Job(
            workspace_id=WS,
            kind="parse_questionnaire",
            status=JobStatus.RUNNING.value,
            payload='{"storage_key": "%s"}' % payload_key,
        )
    )
    db.add(
        Job(
            workspace_id=WS,
            kind="index_document",
            status=JobStatus.COMPLETED.value,
            payload='{"storage_key": "%s"}' % finished_key,
            input_version=finished_key,
        )
    )
    db.commit()

    result = _sweep(db, store, dry_run=False)
    deleted = {key for _bucket, key in result.deleted}
    for key in (
        doc_key,
        archived_key,
        qnr_key,
        export_key,
        trust_key,
        evidence_key,
        pinned_key,
        payload_key,
    ):
        assert key not in deleted
        bucket = store.bucket_exports if key == export_key else store.bucket_raw
        assert store.contains(bucket, key)
    # A finished job is not a reference. Its object is an orphan once no domain row names it.
    assert finished_key in deleted
    assert not store.contains(store.bucket_raw, finished_key)


def test_grace_boundary_keeps_the_equal_and_younger_object(db, store: MemoryStorage):
    equal_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    older_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    younger_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    undated_key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    unknown_key = f"notes/{WS}/{uuid.uuid4().hex}.txt"
    store.put(store.bucket_raw, equal_key, when=NOW - timedelta(seconds=GRACE))
    store.put(store.bucket_raw, older_key, when=NOW - timedelta(seconds=GRACE, microseconds=1))
    store.put(
        store.bucket_raw,
        younger_key,
        when=NOW - timedelta(seconds=GRACE) + timedelta(microseconds=1),
    )
    store.objects[(store.bucket_raw, undated_key)] = {"body": b"x", "last_modified": None}
    store.put(store.bucket_raw, unknown_key, when=NOW - timedelta(days=30))

    result = _sweep(db, store, dry_run=False)
    deleted = {key for _bucket, key in result.deleted}
    assert deleted == {older_key}
    assert store.contains(store.bucket_raw, equal_key)
    assert store.contains(store.bucket_raw, younger_key)
    assert store.contains(store.bucket_raw, undated_key)
    assert store.contains(store.bucket_raw, unknown_key)
    assert not store.contains(store.bucket_raw, older_key)


def test_sweep_dry_run_reports_and_does_not_delete(db, store: MemoryStorage):
    key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    store.put(store.bucket_raw, key, when=NOW - timedelta(seconds=GRACE + 1))
    first = _sweep(db, store, dry_run=True)
    second = _sweep(db, store, dry_run=True)
    assert first.candidates == ((store.bucket_raw, key),)
    assert first.deleted == () and first.dry_run is True
    assert second.candidates == first.candidates
    assert store.contains(store.bucket_raw, key)
    assert store.deletes == []


def test_sweep_execute_is_idempotent(db, store: MemoryStorage):
    key = f"exports/{OTHER}/job-{uuid.uuid4().hex}.xlsx"
    store.put(store.bucket_exports, key, when=NOW - timedelta(seconds=GRACE + 1))
    first = _sweep(db, store, dry_run=False)
    assert first.deleted == ((store.bucket_exports, key),)
    second = _sweep(db, store, dry_run=False)
    assert second.candidates == () and second.deleted == ()
    third = _sweep(db, store, dry_run=True)
    assert third.candidates == ()


def test_cross_workspace_sweep_does_not_touch_the_other_workspace(db, store: MemoryStorage):
    own_orphan = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    other_orphan = f"raw/{OTHER}/{uuid.uuid4().hex}.txt"
    other_live = f"raw/{OTHER}/{uuid.uuid4().hex}.txt"
    old = NOW - timedelta(seconds=GRACE + 10)
    store.put(store.bucket_raw, own_orphan, when=old)
    store.put(store.bucket_raw, other_orphan, when=old)
    store.put(store.bucket_raw, other_live, when=old)
    db.add(
        Document(
            workspace_id=OTHER,
            storage_key=other_live,
            filename="other.txt",
            status="indexed",
        )
    )
    db.commit()

    scoped = _sweep(db, store, dry_run=False, workspace_id=WS)
    assert scoped.deleted == ((store.bucket_raw, own_orphan),)
    assert store.contains(store.bucket_raw, other_orphan)
    assert store.contains(store.bucket_raw, other_live)

    other = _sweep(db, store, dry_run=False, workspace_id=OTHER)
    assert (store.bucket_raw, other_orphan) in other.deleted
    assert (store.bucket_raw, other_live) not in other.deleted
    assert store.contains(store.bucket_raw, other_live)
    assert not store.contains(store.bucket_raw, other_orphan)


def test_list_failure_deletes_nothing(db, store: MemoryStorage):
    key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    store.put(store.bucket_raw, key, when=NOW - timedelta(days=3))
    store.list_error = RuntimeError("synthetic list failure")
    with pytest.raises(RuntimeError, match="synthetic list failure"):
        _sweep(db, store, dry_run=False)
    assert store.contains(store.bucket_raw, key)
    assert store.deletes == []
    missed = sweep_orphans_best_effort(db, store)
    assert missed is None
    assert store.contains(store.bucket_raw, key)


def test_delete_failure_keeps_that_object_and_continues(db, store: MemoryStorage):
    stuck = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    gone = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    old = NOW - timedelta(seconds=GRACE + 5)
    store.put(store.bucket_raw, stuck, when=old)
    store.put(store.bucket_raw, gone, when=old)
    store.fail_delete.add((store.bucket_raw, stuck))
    result = _sweep(db, store, dry_run=False)
    assert (store.bucket_raw, stuck) in result.failed
    assert (store.bucket_raw, gone) in result.deleted
    assert store.contains(store.bucket_raw, stuck)
    assert not store.contains(store.bucket_raw, gone)


def test_reference_recheck_failure_does_not_delete(db, store: MemoryStorage, monkeypatch):
    key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    store.put(store.bucket_raw, key, when=NOW - timedelta(seconds=GRACE + 5))

    def boom(session, found):
        raise RuntimeError("synthetic reference failure")

    monkeypatch.setattr("app.services.storage_reconcile.storage_key_is_referenced", boom)
    result = _sweep(db, store, dry_run=False)
    assert result.deleted == ()
    assert (store.bucket_raw, key) in result.failed
    assert store.contains(store.bucket_raw, key)


def test_reference_that_appears_before_delete_is_spared(db, store: MemoryStorage, monkeypatch):
    key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    store.put(store.bucket_raw, key, when=NOW - timedelta(seconds=GRACE + 5))
    monkeypatch.setattr(
        "app.services.storage_reconcile.storage_key_is_referenced",
        lambda session, found: True,
    )
    result = _sweep(db, store, dry_run=False)
    assert (store.bucket_raw, key) in result.spared
    assert result.deleted == ()
    assert store.contains(store.bucket_raw, key)


def test_reference_read_failure_refuses_the_immediate_delete(db, store: MemoryStorage, monkeypatch):
    key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    store.put(store.bucket_raw, key, when=NOW)

    def boom(session, found):
        raise RuntimeError("synthetic reference failure")

    monkeypatch.setattr("app.services.storage_reconcile.storage_key_is_referenced", boom)
    assert discard_if_unreferenced(db, store, store.bucket_raw, key) is False
    assert store.contains(store.bucket_raw, key)


# --------------------------------------------------------------------------------------------------
# Permission: no HTTP route; the CLI is dry-run unless --execute is passed
# --------------------------------------------------------------------------------------------------


def test_reconcile_is_not_an_http_route(client: TestClient):
    paths = ("/api/storage/reconcile", "/api/admin/storage-reconcile")
    for path in paths:
        assert client.get(path).status_code == 404
        assert client.post(path).status_code == 404
    _login(client, "editor@trust.local", "e")
    for path in paths:
        assert client.post(path).status_code == 404
        assert client.delete(path).status_code == 404
    _login(client, "admin@trust.local", "a")
    for path in paths:
        denied = client.post(path)
        assert denied.status_code == 404
        assert "execute" not in denied.text.lower()


def test_cli_dry_run_is_the_default_and_execute_is_explicit(db, store: MemoryStorage, capsys):
    own = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    other = f"raw/{OTHER}/{uuid.uuid4().hex}.txt"
    old = NOW - timedelta(seconds=GRACE + 5)
    store.put(store.bucket_raw, own, when=old)
    store.put(store.bucket_raw, other, when=old)

    assert execute_cli([], session=db, storage=store) == 0
    assert "dry-run" in capsys.readouterr().out
    assert store.contains(store.bucket_raw, own)
    assert store.contains(store.bucket_raw, other)

    code = execute_cli(["--execute", "--workspace-id", str(WS)], session=db, storage=store)
    assert code == 0
    assert not store.contains(store.bucket_raw, own)
    assert store.contains(store.bucket_raw, other)
    assert "execute" in capsys.readouterr().out


def test_cli_rejects_a_bad_workspace_and_a_failed_sweep(db, store: MemoryStorage, capsys):
    key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    store.put(store.bucket_raw, key, when=NOW - timedelta(days=2))
    with pytest.raises(SystemExit):
        execute_cli(["--workspace-id", "nope"], session=db, storage=store)
    assert store.contains(store.bucket_raw, key)

    store.list_error = RuntimeError("synthetic list failure")
    assert execute_cli(["--execute"], session=db, storage=store) == 2
    assert store.contains(store.bucket_raw, key)
    assert store.deletes == []


def test_cli_enqueue_missing_is_opt_in(db, store: MemoryStorage, capsys):
    qnr = Questionnaire(
        workspace_id=OTHER,
        storage_key=f"raw/{OTHER}/{uuid.uuid4().hex}.xlsx",
        filename="other.xlsx",
        status="uploaded",
    )
    db.add(qnr)
    db.commit()
    assert execute_cli([], session=db, storage=store) == 0
    assert _jobs_for(db, "parse_questionnaire", "questionnaire_id", qnr.id) == []
    assert execute_cli(["--enqueue-missing"], session=db, storage=store) == 0
    assert len(_jobs_for(db, "parse_questionnaire", "questionnaire_id", qnr.id)) == 1
    assert "parse_questionnaire=" in capsys.readouterr().out


def test_orphan_grace_clamps(monkeypatch):
    import app.core.orphan_grace as mod

    monkeypatch.setattr(mod, "_grace_clamp_logged", False)
    monkeypatch.setattr(mod, "_grace_runtime_logged", False)
    monkeypatch.delenv("STORAGE_ORPHAN_GRACE_SECONDS", raising=False)
    assert orphan_grace_seconds() == 7200
    monkeypatch.setenv("STORAGE_ORPHAN_GRACE_SECONDS", "nope")
    assert orphan_grace_seconds() == 7200
    monkeypatch.setenv("STORAGE_ORPHAN_GRACE_SECONDS", "1")
    assert orphan_grace_seconds() == 60
    monkeypatch.setenv("STORAGE_ORPHAN_GRACE_SECONDS", "99999999")
    assert orphan_grace_seconds() == 7 * 24 * 3600


def test_idle_sweep_waits_out_the_grace(monkeypatch):
    from app import worker

    calls: list[int] = []

    def fake_sweep(session, storage=None):
        calls.append(1)
        return None

    class _Session:
        def close(self) -> None:
            return None

    monkeypatch.setattr("app.services.storage_reconcile.sweep_orphans_best_effort", fake_sweep)
    monkeypatch.setattr("app.services.storage_reconcile.orphan_grace_seconds", lambda: 7200)
    monkeypatch.setattr(worker, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(worker, "_last_orphan_sweep_monotonic", time.monotonic())
    worker._maybe_sweep_orphans()
    assert calls == []
    monkeypatch.setattr(worker, "_last_orphan_sweep_monotonic", 0.0)
    worker._maybe_sweep_orphans()
    assert calls == [1]


def test_negative_grace_and_workspace_are_rejected(db, store: MemoryStorage):
    with pytest.raises(ValueError):
        _sweep(db, store, grace_seconds=-1)
    with pytest.raises(ValueError):
        _sweep(db, store, workspace_id=0)
