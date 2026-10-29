"""TC-10-003c: an upload's row, job, and idempotency result commit together.

A retryable enqueue 409 must not leave a committed row or a stored object behind. Every test uses
synthetic bytes, an in-memory fake object store, and the local ``*_test`` database. No network and
no provider calls.
"""

from __future__ import annotations

import logging
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, text

from app.core.database import SessionLocal
from app.models import Document, Job, JobStatus, Questionnaire
from app.services import job_effects as je

WS = 1
_REPLAY_FIELDS = ("id", "job_id", "display_id", "storage_key")
# Must match app.services.upload_enqueue.UPLOAD_IDEMPOTENCY_RESOURCE. The row does not exist yet
# when the client key is claimed, so the scope's resource slot is this constant.
_UPLOAD_RESOURCE = "new"

_ROUTES = (
    pytest.param("documents", id="documents"),
    pytest.param("questionnaires", id="questionnaires"),
)


def _route(name: str) -> dict:
    if name == "documents":
        return {
            "url": "/api/documents/upload",
            "model": Document,
            "kind": "index_document",
            "scope": "documents.upload",
            "module": "app.api.routes.documents",
        }
    return {
        "url": "/api/questionnaires/upload",
        "model": Questionnaire,
        "kind": "parse_questionnaire",
        "scope": "questionnaires.upload",
        "module": "app.api.routes.questionnaires",
    }


@pytest.fixture
def db(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    session = SessionLocal()
    tables = ("documents", "questionnaires", "jobs", "idempotency_keys")
    marks = {
        table: int(session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar() or 0)
        for table in tables
    }
    try:
        yield session
    finally:
        try:
            session.rollback()
            for table, mark in marks.items():
                session.execute(text(f"DELETE FROM {table} WHERE id > :m"), {"m": mark})
            session.commit()
        finally:
            session.close()


@pytest.fixture
def store():
    """In-memory fake object store patched over StorageClient.upload and delete."""
    state = {"data": {}, "fail_delete": False, "deletes": 0}
    lock = threading.Lock()

    def upload(self, bucket, key, body, **kwargs):
        content = body.read() if hasattr(body, "read") else body
        with lock:
            state["data"][(bucket, key)] = content
        return key

    def delete(self, bucket, key):
        with lock:
            state["deletes"] += 1
            if state["fail_delete"]:
                raise RuntimeError("synthetic delete failure")
            state["data"].pop((bucket, key), None)

    with (
        patch("app.services.storage.StorageClient.upload", upload),
        patch("app.services.storage.StorageClient.delete", delete),
    ):
        yield state


def _login(client: TestClient) -> str:
    response = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert response.status_code == 200, response.text
    cookie = client.cookies.get("tc_session")
    assert cookie
    return cookie


def _post(
    client: TestClient,
    route: dict,
    *,
    content: bytes = b"Synthetic evidence text for TC-10-003c.",
    name: str = "synthetic.txt",
    key: str | None = None,
    workspace_id: int = WS,
):
    headers = {}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(
        route["url"],
        data={"workspace_id": str(workspace_id)},
        files={"file": (name, content, "text/plain")},
        headers=headers,
    )


def _mark(db, model) -> int:
    db.rollback()
    return int(db.query(func.max(model.id)).scalar() or 0)


def _rows(db, model, mark: int):
    db.rollback()
    return db.query(model).filter(model.id > mark).order_by(model.id).all()


def _idem_since(db, mark: int) -> int:
    db.rollback()
    return int(
        db.execute(
            text("SELECT COUNT(*) FROM idempotency_keys WHERE id > :m"),
            {"m": mark},
        ).scalar()
        or 0
    )


def _owner_of(db, key: str):
    from app.core import idempotency

    db.rollback()
    return db.execute(
        idempotency.text("SELECT owner_token FROM idempotency_keys WHERE idempotency_key = :k"),
        {"k": key},
    ).scalar()


def _expire_claim(db, key: str) -> None:
    from app.core import idempotency

    db.execute(
        idempotency.text("UPDATE idempotency_keys SET expires_at = :t WHERE idempotency_key = :k"),
        {"t": datetime.now(timezone.utc) - timedelta(seconds=5), "k": key},
    )
    db.commit()


def _hold_queued_slot(db, kind: str) -> tuple[str, int]:
    key = f"{kind}:hold-{uuid.uuid4().hex}"
    job = Job(
        workspace_id=WS,
        kind=kind,
        status=JobStatus.QUEUED.value,
        payload='{"hold": true}',
        idempotency_key=key,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return key, job.id


@contextmanager
def _force_enqueue_conflict(route: dict, hold_key: str):
    """Make enqueue_job lose the queued-slot race on both attempts."""

    def fixed_key(*args, **kwargs):
        return hold_key

    with (
        patch(f"{route['module']}.job_idempotency_key", side_effect=fixed_key),
        patch("app.services.job_effects._queued_with_key", return_value=None),
    ):
        yield


def _assert_retryable_conflict(response) -> None:
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "idempotency_conflict"
    assert body["error"]["retryable"] is True
    assert body["detail"] == body["error"]["message"]
    assert response.headers["Retry-After"] == "1"
    assert "IntegrityError" not in response.text


def _thread_client(session_cookie: str) -> TestClient:
    from app.main import app

    client = TestClient(app, base_url="http://localhost")
    client.cookies.set("tc_session", session_cookie)
    return client


def _run_together(calls):
    barrier = threading.Barrier(len(calls))
    errors: list[BaseException] = []
    results: list = [None] * len(calls)

    def worker(index: int, fn) -> None:
        try:
            barrier.wait(timeout=20)
            results[index] = fn()
        except BaseException as exc:  # noqa: BLE001 - asserted by the caller
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i, fn)) for i, fn in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert all(item is not None for item in results)
    return results


# ---------------------------------------------------------------------------------------------------------
# enqueue_job(commit=False) and idempotency.set(commit=False)
# ---------------------------------------------------------------------------------------------------------


def test_enqueue_job_commit_false_leaves_commit_to_the_caller(db):
    key = je.job_idempotency_key("index_document", WS, uuid.uuid4().hex)
    doc = Document(
        workspace_id=WS,
        storage_key=f"raw/{WS}/{uuid.uuid4().hex}.txt",
        filename="synthetic.txt",
        status="uploaded",
    )
    db.add(doc)
    db.flush()
    job, created = je.enqueue_job(
        db,
        workspace_id=WS,
        kind="index_document",
        payload={"document_id": doc.id},
        idempotency_key=key,
        commit=False,
    )
    assert created is True and job.id
    job_id, doc_id = job.id, doc.id
    other = SessionLocal()
    try:
        assert other.query(Job).filter(Job.id == job_id).first() is None
        assert other.query(Document).filter(Document.id == doc_id).first() is None
    finally:
        other.close()
    db.rollback()
    other = SessionLocal()
    try:
        assert other.query(Job).filter(Job.id == job_id).first() is None
        assert other.query(Document).filter(Document.id == doc_id).first() is None
        doc2 = Document(
            workspace_id=WS,
            storage_key=f"raw/{WS}/{uuid.uuid4().hex}.txt",
            filename="synthetic-2.txt",
            status="uploaded",
        )
        db.add(doc2)
        db.flush()
        job2, created2 = je.enqueue_job(
            db,
            workspace_id=WS,
            kind="index_document",
            payload={"document_id": doc2.id},
            idempotency_key=je.job_idempotency_key("index_document", WS, uuid.uuid4().hex),
            commit=False,
        )
        assert created2 is True
        assert other.query(Job).filter(Job.id == job2.id).first() is None
        db.commit()
        assert other.query(Job).filter(Job.id == job2.id).one().idempotency_key
        assert (
            other.query(Document).filter(Document.id == doc2.id).one().filename == "synthetic-2.txt"
        )
    finally:
        other.close()


def test_enqueue_conflict_with_commit_false_rolls_back_the_callers_row(db):
    key = je.job_idempotency_key("index_document", WS, uuid.uuid4().hex)
    winner, created = je.enqueue_job(
        db,
        workspace_id=WS,
        kind="index_document",
        payload={"hold": True},
        idempotency_key=key,
    )
    assert created is True
    doc = Document(
        workspace_id=WS,
        storage_key=f"raw/{WS}/{uuid.uuid4().hex}.txt",
        filename="rolled-back.txt",
        status="uploaded",
    )
    db.add(doc)
    db.flush()
    doc_id = doc.id
    with patch.object(je, "_queued_with_key", return_value=None):
        with pytest.raises(je.EnqueueConflictError):
            je.enqueue_job(
                db,
                workspace_id=WS,
                kind="index_document",
                payload={"document_id": doc_id},
                idempotency_key=key,
                commit=False,
            )
    assert db.query(Document).filter(Document.id == doc_id).first() is None
    assert db.query(Job).filter(Job.id == winner.id).one().status == JobStatus.QUEUED.value
    db.commit()
    assert db.query(Document).filter(Document.id == doc_id).first() is None


def test_idempotency_set_commit_false_is_atomic_with_caller_and_fenced(db):
    from app.core import idempotency

    key = f"atomic-{uuid.uuid4().hex}"
    owner = idempotency.claim(db, key)
    assert owner
    doc = Document(
        workspace_id=WS,
        storage_key=f"raw/{WS}/{uuid.uuid4().hex}.txt",
        filename="atomic.txt",
        status="uploaded",
    )
    db.add(doc)
    db.flush()
    assert idempotency.set(db, key, 200, {"id": doc.id}, owner=owner, commit=False) is True
    other = SessionLocal()
    try:
        assert other.query(Document).filter(Document.id == doc.id).first() is None
        assert idempotency.get(other, key) is None
        db.commit()
        assert other.query(Document).filter(Document.id == doc.id).one().filename == "atomic.txt"
        assert idempotency.get(other, key) == (200, {"id": doc.id})
    finally:
        other.close()

    key2 = f"fence-{uuid.uuid4().hex}"
    stale = idempotency.claim(db, key2)
    _expire_claim(db, key2)
    other = SessionLocal()
    try:
        fresh = idempotency.claim(other, key2)
        assert stale and fresh and stale != fresh
        doc2 = Document(
            workspace_id=WS,
            storage_key=f"raw/{WS}/{uuid.uuid4().hex}.txt",
            filename="fenced.txt",
            status="uploaded",
        )
        db.add(doc2)
        db.flush()
        with pytest.raises(Exception) as exc_info:
            idempotency.set(db, key2, 200, {"id": doc2.id}, owner=stale, commit=False)
        assert type(exc_info.value).__name__ == "IdempotencyClaimLost"
        # The caller still owns the rollback: the row is pending here and invisible elsewhere.
        assert db.query(Document).filter(Document.id == doc2.id).one()
        assert other.query(Document).filter(Document.id == doc2.id).first() is None
        assert idempotency.get(other, key2) is None
        assert _owner_of(other, key2) == fresh
        db.rollback()
        assert other.query(Document).filter(Document.id == doc2.id).first() is None
        assert idempotency.set(other, key2, 200, {"kept": True}, owner=fresh) is True
        assert idempotency.get(other, key2) == (200, {"kept": True})
        assert idempotency.set(db, key2, 200, {"kept": False}, owner=stale) is False
        assert idempotency.get(other, key2) == (200, {"kept": True})
    finally:
        other.close()


# ---------------------------------------------------------------------------------------------------------
# Both upload routes
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("route_name", _ROUTES)
def test_enqueue_conflict_409_leaves_no_row_job_or_object_and_retry_creates_one(
    client, db, store, route_name
):
    route = _route(route_name)
    _login(client)
    model_mark = _mark(db, route["model"])
    job_mark = _mark(db, Job)
    hold_key, hold_id = _hold_queued_slot(db, route["kind"])
    with _force_enqueue_conflict(route, hold_key):
        conflicted = _post(client, route, content=b"Synthetic conflict upload.")
    _assert_retryable_conflict(conflicted)
    assert _rows(db, route["model"], model_mark) == []
    assert [job.id for job in _rows(db, Job, job_mark)] == [hold_id]
    assert store["data"] == {}

    retry = _post(client, route, content=b"Synthetic conflict retry.")
    assert retry.status_code == 200, retry.text
    body = retry.json()
    rows = _rows(db, route["model"], model_mark)
    assert len(rows) == 1
    assert body["id"] == rows[0].id
    assert body["display_id"] == rows[0].display_id
    assert body["storage_key"] == rows[0].storage_key
    assert body["job_id"]
    jobs = _rows(db, Job, job_mark)
    assert {job.id for job in jobs} == {hold_id, body["job_id"]}
    assert len(store["data"]) == 1


@pytest.mark.parametrize("route_name", _ROUTES)
def test_idempotency_key_retry_after_409_and_replay_never_duplicate(client, db, store, route_name):
    route = _route(route_name)
    _login(client)
    model_mark = _mark(db, route["model"])
    hold_key, _hold_id = _hold_queued_slot(db, route["kind"])
    client_key = f"retry-{uuid.uuid4().hex}"
    with _force_enqueue_conflict(route, hold_key):
        conflicted = _post(client, route, key=client_key, content=b"Synthetic first attempt.")
    _assert_retryable_conflict(conflicted)
    assert _rows(db, route["model"], model_mark) == []
    assert store["data"] == {}

    created = _post(client, route, key=client_key, content=b"Synthetic retry body.")
    assert created.status_code == 200, created.text
    replay = _post(client, route, key=client_key, content=b"Synthetic different body.")
    assert replay.status_code == 200, replay.text
    assert replay.json() == created.json()
    for field in _REPLAY_FIELDS:
        assert replay.json()[field] == created.json()[field]
    rows = _rows(db, route["model"], model_mark)
    assert len(rows) == 1
    assert rows[0].id == created.json()["id"]
    assert rows[0].storage_key == created.json()["storage_key"]
    assert rows[0].display_id == created.json()["display_id"]
    assert len(store["data"]) == 1


@pytest.mark.parametrize("route_name", _ROUTES)
def test_storage_delete_failure_still_returns_409_without_a_row(
    client, db, store, route_name, caplog
):
    route = _route(route_name)
    _login(client)
    model_mark = _mark(db, route["model"])
    hold_key, _hold_id = _hold_queued_slot(db, route["kind"])
    store["fail_delete"] = True
    with caplog.at_level(logging.WARNING, logger="app.services.upload_enqueue"):
        with _force_enqueue_conflict(route, hold_key):
            conflicted = _post(client, route, content=b"Synthetic delete failure.")
    _assert_retryable_conflict(conflicted)
    assert _rows(db, route["model"], model_mark) == []
    assert store["data"], "the failed delete leaves the object; the row must still be gone"
    assert store["deletes"] >= 1
    assert "failed to delete stored object" in caplog.text


@pytest.mark.parametrize("route_name", _ROUTES)
def test_lost_idempotency_claim_rolls_back_the_upload(client, db, store, route_name):
    from app.core import idempotency

    route = _route(route_name)
    _login(client)
    model_mark = _mark(db, route["model"])
    client_key = f"lost-{uuid.uuid4().hex}"
    scoped = idempotency.scoped_key(WS, route["scope"], _UPLOAD_RESOURCE, client_key)
    stolen: dict[str, str | None] = {}
    real_enqueue = __import__(route["module"], fromlist=["enqueue_job"]).enqueue_job

    def steal_after_enqueue(*args, **kwargs):
        outcome = real_enqueue(*args, **kwargs)
        side = SessionLocal()
        try:
            _expire_claim(side, scoped)
            stolen["owner"] = idempotency.claim(side, scoped)
        finally:
            side.close()
        return outcome

    with patch(f"{route['module']}.enqueue_job", side_effect=steal_after_enqueue):
        response = _post(client, route, key=client_key, content=b"Synthetic lost claim.")
    _assert_retryable_conflict(response)
    assert stolen["owner"]
    assert _rows(db, route["model"], model_mark) == []
    assert store["data"] == {}
    assert _owner_of(db, scoped) == stolen["owner"]
    assert idempotency.get(db, scoped) is None


@pytest.mark.parametrize("route_name", _ROUTES)
def test_forbidden_and_invalid_key_store_nothing(client, db, store, route_name):
    route = _route(route_name)
    _login(client)
    model_mark = _mark(db, route["model"])
    idem_mark = int(
        db.execute(text("SELECT COALESCE(MAX(id), 0) FROM idempotency_keys")).scalar() or 0
    )
    forbidden = _post(client, route, workspace_id=2, content=b"Synthetic forbidden upload.")
    assert forbidden.status_code == 403
    assert "denied" in (forbidden.json().get("detail") or "").lower()

    invalid = _post(client, route, key="bad key", content=b"Synthetic invalid key.")
    assert invalid.status_code == 400, invalid.text
    assert invalid.json()["error"]["code"] == "invalid_idempotency_key"
    empty = _post(client, route, key="", content=b"Synthetic empty key.")
    assert empty.status_code == 400, empty.text
    assert empty.json()["error"]["code"] == "invalid_idempotency_key"

    assert _rows(db, route["model"], model_mark) == []
    assert _idem_since(db, idem_mark) == 0
    assert store["data"] == {}


@pytest.mark.parametrize("route_name", _ROUTES)
def test_concurrent_same_key_uploads_create_exactly_one_row(client, db, store, route_name):
    route = _route(route_name)
    cookie = _login(client)
    model_mark = _mark(db, route["model"])
    client_key = f"same-{uuid.uuid4().hex}"
    clients = [_thread_client(cookie), _thread_client(cookie)]
    try:

        def call(index: int):
            return _post(
                clients[index],
                route,
                key=client_key,
                name=f"synthetic-{index}.txt",
                content=f"Synthetic concurrent {index}.".encode(),
            )

        responses = _run_together([lambda index=i: call(index) for i in range(2)])
    finally:
        for item in clients:
            item.close()

    rows = _rows(db, route["model"], model_mark)
    assert len(rows) == 1
    replay = _post(client, route, key=client_key, content=b"Synthetic replay after race.")
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == rows[0].id
    for field in _REPLAY_FIELDS:
        assert replay.json()[field]
    assert len(_rows(db, route["model"], model_mark)) == 1
    saw_success = False
    for response in responses:
        if response.status_code == 200:
            saw_success = True
            assert response.json()["id"] == rows[0].id
            assert response.json()["storage_key"] == rows[0].storage_key
        else:
            assert response.status_code == 409
    assert saw_success or replay.status_code == 200


@pytest.mark.parametrize("route_name", _ROUTES)
def test_concurrent_conflicting_uploads_leave_nothing_then_retries_create_one_each(
    client, db, store, route_name
):
    route = _route(route_name)
    cookie = _login(client)
    model_mark = _mark(db, route["model"])
    hold_key, _hold_id = _hold_queued_slot(db, route["kind"])
    clients = [_thread_client(cookie), _thread_client(cookie)]
    try:
        with _force_enqueue_conflict(route, hold_key):

            def call(index: int):
                return _post(
                    clients[index],
                    route,
                    name=f"conflict-{index}.txt",
                    content=f"Synthetic conflicting {index}.".encode(),
                )

            responses = _run_together([lambda index=i: call(index) for i in range(2)])
    finally:
        for item in clients:
            item.close()

    for response in responses:
        _assert_retryable_conflict(response)
    assert _rows(db, route["model"], model_mark) == []
    assert store["data"] == {}

    first = _post(client, route, name="retry-a.txt", content=b"Synthetic retry A.")
    second = _post(client, route, name="retry-b.txt", content=b"Synthetic retry B.")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] != second.json()["id"]
    rows = _rows(db, route["model"], model_mark)
    assert {row.id for row in rows} == {first.json()["id"], second.json()["id"]}
    assert len(rows) == 2
    assert len(store["data"]) == 2
