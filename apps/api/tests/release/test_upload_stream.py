"""TC-07-006: uploads stop at MAX_UPLOAD_BYTES and leave nothing behind.

The bounded reader, the production Caddy limit, and the Next.js proxy are the
same cap (default 52428800). A body past that cap is HTTP 413. The bytes past
the cap are not kept, and a rejected or interrupted upload does not insert a
document, questionnaire, trust request, or job, and does not store an object.

On the pre-fix tree ``upload_raw`` calls ``file.file.read()`` with no size, so
the stream is drained and the overflow stays in a local. These checks fail there.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import anyio
import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Document, Job, Questionnaire, TrustRequest
from app.services.file_service import FileService

CANARY = b"OVERFLOW-CANARY-TC07006"
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[4]
WS = 1
_KEPT_FRAMES = {"upload_raw", "upload_trust_request_attachment", "read_bounded_upload"}
_SKIP_LOCALS = {"file", "fileobj", "self", "document"}


class _Memory:
    def __init__(self) -> None:
        self.bucket_raw = "raw"
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload(self, bucket: str, key: str, body: bytes, content_type: str | None = None) -> str:
        data = body.read() if hasattr(body, "read") else body
        self.objects[(bucket, key)] = data
        return key


class _Probe:
    """A file object that records every read size and honours it."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.pos = 0
        self.calls: list[int] = []

    def read(self, n: int = -1) -> bytes:
        self.calls.append(-1 if n is None else int(n))
        if n is None or n < 0:
            n = len(self.payload) - self.pos
        chunk = self.payload[self.pos : self.pos + n]
        self.pos += len(chunk)
        return chunk


class _Greedy:
    """Returns the whole overflow on every read, whatever size was asked for."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[int] = []

    def read(self, n: int = -1) -> bytes:
        self.calls.append(-1 if n is None else int(n))
        return self.payload


def _holds(value: object, needle: bytes) -> bool:
    if isinstance(value, (bytes, bytearray)):
        return needle in value
    if isinstance(value, memoryview):
        return needle in value.tobytes()
    if isinstance(value, str):
        return needle.decode() in value
    if isinstance(value, (list, tuple)):
        return any(_holds(item, needle) for item in value)
    if isinstance(value, dict):
        return any(_holds(item, needle) for item in value.values())
    return False


def _kept(exc: BaseException, needle: bytes) -> bool:
    """True when a reader frame still holds the overflow bytes."""
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_name in _KEPT_FRAMES:
            for name, value in tb.tb_frame.f_locals.items():
                if name in _SKIP_LOCALS:
                    continue
                if _holds(value, needle):
                    return True
        tb = tb.tb_next
    return False


def _reject(service: FileService, kind: str, upload: UploadFile) -> None:
    if kind == "raw":
        service.upload_raw(WS, upload)
        return
    service.upload_trust_request_attachment(WS, 7, upload)


@pytest.fixture
def db(client):
    """Marks taken after seed. Rows this test inserts are removed afterwards."""
    session = SessionLocal()
    models = (Document, Questionnaire, Job, TrustRequest)
    marks = {model: int(session.query(func.max(model.id)).scalar() or 0) for model in models}
    try:
        yield session, marks
    finally:
        session.rollback()
        for model, mark in marks.items():
            session.query(model).filter(model.id > mark).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def store():
    state: dict[str, dict] = {"objects": {}}

    def upload(self, bucket, key, body, content_type=None):
        data = body.read() if hasattr(body, "read") else body
        state["objects"][(bucket, key)] = data
        return key

    def delete(self, bucket, key):
        state["objects"].pop((bucket, key), None)

    with (
        patch("app.services.storage.StorageClient.upload", upload),
        patch("app.services.storage.StorageClient.delete", delete),
    ):
        yield state


def _login(client) -> None:
    response = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert response.status_code == 200, response.text


def _added(session: Session, marks: dict) -> dict[str, int]:
    session.rollback()
    return {
        model.__tablename__: session.query(model).filter(model.id > mark).count()
        for model, mark in marks.items()
    }


def _post(client, kind: str, payload: bytes, email: str):
    if kind == "trust":
        return client.post(
            "/api/trust-requests/submit",
            data={
                "requester_email": email,
                "message": "Please review this synthetic file.",
                "workspace_id": str(WS),
            },
            files={"document": ("note.txt", payload, "text/plain")},
        )
    url = "/api/documents/upload" if kind == "documents" else "/api/questionnaires/upload"
    return client.post(
        url,
        data={"workspace_id": str(WS)},
        files={"file": ("note.txt", payload, "text/plain")},
    )


def test_proxy_and_api_share_the_upload_limit() -> None:
    """Caddy, the Next proxy, and the API default are one number: 52428800."""
    assert DEFAULT_MAX_UPLOAD_BYTES == 52428800
    config = (REPO_ROOT / "apps/api/app/core/config.py").read_text(encoding="utf-8")
    assert "50 * 1024 * 1024" in config
    caddy = (REPO_ROOT / "infra/caddy/Caddyfile.production").read_text(encoding="utf-8")
    api_block = caddy.split("handle /api*", 1)[1].split("\n    handle ", 1)[0]
    assert "request_body" in api_block
    assert "max_size {$MAX_UPLOAD_BYTES:52428800}" in api_block
    compose = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    caddy_service = compose.split("  caddy:", 1)[1].split("\n  web:", 1)[0]
    assert "MAX_UPLOAD_BYTES:" in caddy_service
    web = (REPO_ROOT / "apps/web/lib/upload-limit.ts").read_text(encoding="utf-8")
    assert "MAX_UPLOAD_BYTES" in web
    assert "50 * 1024 * 1024" in web
    route = (REPO_ROOT / "apps/web/app/api/[[...path]]/route.ts").read_text(encoding="utf-8")
    assert "request.arrayBuffer()" not in route
    assert "duplex: 'half'" in route


def test_uploads_share_one_bounded_reader() -> None:
    """Document, questionnaire, and trust intake must not call an unbounded read."""
    service = (REPO_ROOT / "apps/api/app/services/file_service.py").read_text(encoding="utf-8")
    trust = (REPO_ROOT / "apps/api/app/api/routes/trust_requests.py").read_text(encoding="utf-8")
    questionnaires = (REPO_ROOT / "apps/api/app/api/routes/questionnaires.py").read_text(
        encoding="utf-8"
    )
    assert "def read_bounded_upload" in service
    assert service.count("read_bounded_upload(") >= 3
    assert "file.file.read()" not in service
    assert "read_bounded_upload(" in trust
    assert "document.file.read(" not in trust
    assert "file.file.read()" not in questionnaires


@pytest.mark.parametrize("kind", ["raw", "trust"])
def test_over_delivery_is_not_retained(monkeypatch, kind: str) -> None:
    """A read that returns more than the cap is dropped, not stored on the frame."""
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 32)
    payload = b"A" * 64 + CANARY
    greedy = _Greedy(payload)
    memory = _Memory()
    with pytest.raises(HTTPException) as caught:
        _reject(FileService(memory), kind, UploadFile(filename="note.txt", file=greedy))
    assert caught.value.status_code == 413
    assert CANARY.decode() not in str(caught.value.detail)
    assert greedy.calls
    assert all(call > 0 for call in greedy.calls)
    assert greedy.calls[0] <= 32
    assert not _kept(caught.value, CANARY)
    assert memory.objects == {}


@pytest.mark.parametrize("kind", ["raw", "trust"])
def test_respecting_stream_stops_at_the_first_extra_byte(monkeypatch, kind: str) -> None:
    """The reader asks for a size and does not drain the rest of an oversized body."""
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 32)
    payload = b"B" * 32 + CANARY
    probe = _Probe(payload)
    memory = _Memory()
    with pytest.raises(HTTPException) as caught:
        _reject(FileService(memory), kind, UploadFile(filename="note.txt", file=probe))
    assert caught.value.status_code == 413
    assert CANARY.decode() not in str(caught.value.detail)
    assert probe.pos <= 33
    assert all(call > 0 for call in probe.calls)
    assert not _kept(caught.value, CANARY)
    assert memory.objects == {}


@pytest.mark.parametrize("kind", ["raw", "trust"])
def test_exact_limit_is_stored(monkeypatch, kind: str) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 32)
    payload = b"C" * 32
    memory = _Memory()
    service = FileService(memory)
    if kind == "raw":
        key, name = service.upload_raw(WS, UploadFile(filename="note.txt", file=_Probe(payload)))
        assert name == "note.txt"
    else:
        key, name, size = service.upload_trust_request_attachment(
            WS, 7, UploadFile(filename="note.txt", file=_Probe(payload))
        )
        assert name == "note.txt"
        assert size == 32
    assert memory.objects[(memory.bucket_raw, key)] == payload


@pytest.mark.parametrize("kind", ["documents", "questionnaires", "trust"])
@pytest.mark.parametrize("length", ["under", "exact"])
def test_body_at_or_under_the_limit_is_accepted(
    client, db, store, monkeypatch, kind: str, length: str
) -> None:
    limit = 64
    monkeypatch.setattr(get_settings(), "max_upload_bytes", limit)
    if kind != "trust":
        _login(client)
    payload = b"u" * (limit - 1) if length == "under" else b"e" * limit
    session, marks = db
    response = _post(client, kind, payload, f"tc07006-{kind}-{length}@example.com")
    assert response.status_code == 200, response.text
    added = _added(session, marks)
    if kind == "trust":
        assert added["trust_requests"] == 1
        assert added["documents"] == 0
        assert added["questionnaires"] == 0
        assert added["jobs"] == 0
    elif kind == "documents":
        assert added["documents"] == 1
        assert added["jobs"] == 1
    else:
        assert added["questionnaires"] == 1
        assert added["jobs"] == 1
    assert len(store["objects"]) == 1
    assert next(iter(store["objects"].values())) == payload


@pytest.mark.parametrize("kind", ["documents", "questionnaires", "trust"])
def test_body_over_the_limit_is_413_and_leaves_nothing(
    client, db, store, monkeypatch, kind: str
) -> None:
    limit = 64
    monkeypatch.setattr(get_settings(), "max_upload_bytes", limit)
    if kind != "trust":
        _login(client)
    reads: list[tuple[int, int]] = []
    original = tempfile.SpooledTemporaryFile.read

    def spy(self, size: int = -1):
        data = original(self, size)
        reads.append((size, len(data) if data else 0))
        return data

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "read", spy)
    payload = b"o" * limit + CANARY
    session, marks = db
    before = _added(session, marks)
    response = _post(client, kind, payload, f"tc07006-{kind}-over@example.com")
    assert response.status_code == 413, response.text
    assert CANARY.decode() not in response.text
    assert _added(session, marks) == before
    assert store["objects"] == {}
    assert reads
    assert all(size > 0 for size, _n in reads)
    assert sum(n for _size, n in reads) <= limit + 1


@pytest.mark.parametrize("kind", ["documents", "questionnaires", "trust"])
def test_exception_mid_body_leaves_nothing(client, db, store, monkeypatch, kind: str) -> None:
    """A read that raises after the first bytes does not insert a row or store an object."""
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 64)
    if kind != "trust":
        _login(client)
    original = tempfile.SpooledTemporaryFile.read

    def explode(self, size: int = -1):
        data = original(self, size)
        if data:
            raise ConnectionError("client gone mid-body")
        return data

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "read", explode)
    session, marks = db
    before = _added(session, marks)
    with pytest.raises(ConnectionError, match="mid-body"):
        _post(client, kind, b"partial-body-text", f"tc07006-{kind}-boom@example.com")
    assert _added(session, marks) == before
    assert store["objects"] == {}


def _drive_disconnect(path: str, header_pairs: list[tuple[bytes, bytes]], body: bytes) -> None:
    from app.main import app

    steps = [
        {"type": "http.request", "body": body, "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive():
        if steps:
            return steps.pop(0)
        return {"type": "http.disconnect"}

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": header_pairs,
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 80),
    }

    async def run():
        with anyio.fail_after(5):
            await app(scope, receive, send)

    try:
        anyio.run(run)
    except Exception:
        return


@pytest.mark.parametrize("kind", ["documents", "questionnaires", "trust"])
def test_client_disconnect_mid_body_leaves_nothing(client, db, store, kind: str) -> None:
    if kind != "trust":
        _login(client)
    cookie = client.cookies.get("tc_session")
    boundary = "----tc07006bound"
    if kind == "trust":
        head = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="requester_email"\r\n\r\n'
            f"tc07006-{kind}-drop@example.com\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="message"\r\n\r\n'
            "Please review.\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="workspace_id"\r\n\r\n'
            "1\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="document"; filename="note.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        )
        path = "/api/trust-requests/submit"
    else:
        head = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="workspace_id"\r\n\r\n'
            "1\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="note.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        )
        path = "/api/documents/upload" if kind == "documents" else "/api/questionnaires/upload"
    headers = [
        (b"host", b"localhost"),
        (b"origin", b"http://localhost"),
        (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
    ]
    if cookie:
        headers.append((b"cookie", f"tc_session={cookie}".encode()))
    session, marks = db
    before = _added(session, marks)
    _drive_disconnect(path, headers, head.encode() + b"partial")
    assert _added(session, marks) == before
    assert store["objects"] == {}
