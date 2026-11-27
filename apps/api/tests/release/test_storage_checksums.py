"""TC-10-006 storage checksums on PostgreSQL.

A document and a completed export stream only when the recorded SHA-256 matches
the object bytes and the recorded version, media type, and workspace agree.
A missing hash, a mismatch, a missing object, and a key that names another
workspace are refused. The refusal is a fixed error: no storage key and no
hash in the body, and ``X-Content-Type-Options: nosniff``.

Rows with a null hash stay refused until ``backfill_storage_checksums`` runs
with ``execute=True``. A row whose hash, media type, and positive version
already agree is left as it is, including when that version is above 1.
This file is not skipped. CI runs it with TC_REQUIRE_DB=1.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.core.password import hash_password
from app.models import Document, ExportRecord, Job, User, UserSession, WorkspaceMember
from app.services.export_service import XLSX_MEDIA_TYPE

_DETAIL = "The stored file could not be verified."

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "tc10006_storage_checksums"
PARENT = "tc20050_crm_pipeline_sync"
_PDF = "application/pdf"
_LOGIN = "synthetic-checksum-10006"
_OWN = b"%PDF-1.4 synthetic owned document"
_EXPORT = b"PK\x03\x04 synthetic hashed export"
_OTHER = b"PK\x03\x04 other export bytes"
_FOREIGN = b"%PDF-1.4 FOREIGN-DOCUMENT-BYTES"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Store:
    def __init__(self) -> None:
        self.bucket_raw = "raw"
        self.bucket_exports = "exports"
        self.objects: dict[tuple[str, str], dict] = {}
        self.reads: list[str] = []

    def put(
        self, bucket: str, key: str, body: bytes, *, meta: dict | None = None, media: str = _PDF
    ):
        self.objects[(bucket, key)] = {
            "body": body,
            "meta": {} if meta is None else dict(meta),
            "content_type": media,
        }

    def upload(self, bucket, key, body, content_type=None, metadata=None):
        data = body.read() if hasattr(body, "read") else body
        self.put(
            bucket,
            key,
            bytes(data),
            meta=metadata,
            media=content_type or "application/octet-stream",
        )
        return key

    def download_checksummed(self, bucket, key):
        self.reads.append(key)
        item = self.objects.get((bucket, key))
        if item is None:
            raise FileNotFoundError(key)
        meta = {str(name).lower(): str(value) for name, value in item["meta"].items()}
        meta["content-type"] = item["content_type"]
        return item["body"], meta

    def download(self, bucket, key):
        body, _meta = self.download_checksummed(bucket, key)
        return body

    def download_stream(self, bucket, key):
        self.reads.append(key)
        item = self.objects.get((bucket, key))
        if item is None:
            raise FileNotFoundError(key)
        return iter([item["body"]])


def _meta(workspace_id: int, digest: str, version: int, media: str) -> dict[str, str]:
    return {
        "sha256": digest,
        "version": str(version),
        "workspace-id": str(workspace_id),
        "media-type": media,
    }


def _nosniff(response) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"


def _refused(response, *secrets: bytes, keys: list[str] | None = None) -> None:
    assert response.status_code == 409, response.text
    _nosniff(response)
    text_body = response.text
    assert _DETAIL in text_body or "export_storage_failed" in text_body
    for secret in secrets:
        assert secret not in response.content
    for key in keys or []:
        assert key not in text_body
    assert "sha256" not in text_body.lower()


def _document(client, document_id, workspace_id=1):
    return client.get(
        f"/api/documents/{document_id}/content",
        params={"workspace_id": workspace_id},
    )


def _export(client, record_id, workspace_id=1):
    return client.get(
        f"/api/exports/records/{record_id}/download",
        params={"workspace_id": workspace_id},
    )


def _alembic(*args: str) -> str:
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:] + result.stdout[-2000:]
    return result.stdout


def test_legacy_document_download_is_refused(client, db_session):
    """A document row with no recorded hash is not the file."""
    from app.main import app
    from app.services.storage import get_storage

    suffix = uuid.uuid4().hex[:12]
    storage = _Store()
    email = f"tc10006-legacy-{suffix}@example.com"
    user = User(
        email=email,
        password_hash=hash_password(_LOGIN),
        display_name="Legacy checksum",
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="admin", suspended=False))
    key = f"raw/1/{suffix}-unhashed.pdf"
    storage.put("raw", key, _OWN, media=_PDF)
    row = Document(
        workspace_id=1,
        storage_key=key,
        filename="unhashed.pdf",
        status="uploaded",
    )
    db_session.add(row)
    db_session.commit()
    previous = app.dependency_overrides.get(get_storage)
    app.dependency_overrides[get_storage] = lambda: storage
    signed_in = client.post("/api/auth/login", json={"email": email, "password": _LOGIN})
    assert signed_in.status_code == 200, signed_in.text
    try:
        response = _document(client, row.id)
        assert response.status_code == 409, response.text
        assert response.content != _OWN
        assert key not in response.text
        assert _sha(_OWN) not in response.text
        _nosniff(response)
        assert storage.reads == []
    finally:
        app.dependency_overrides.pop(get_storage, None)
        if previous is not None:
            app.dependency_overrides[get_storage] = previous
        client.cookies.clear()
        db_session.rollback()
        db_session.query(Document).filter(Document.id == row.id).delete(synchronize_session=False)
        db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete(
            synchronize_session=False
        )
        db_session.query(UserSession).filter(UserSession.user_id == user.id).delete(
            synchronize_session=False
        )
        db_session.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db_session.commit()


def test_revision_is_the_single_head_child():
    script = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == PARENT
    heads = list(script.get_heads())
    assert heads == [REVISION]
    source = (API_ROOT / "alembic" / "versions" / "tc10006_storage_checksums.py").read_text()
    assert "import app" not in source and "from app" not in source


def test_upgrade_adds_nullable_columns_and_downgrade_removes_them(migrated_db):
    engine = create_engine(os.environ["DATABASE_URL"])
    created: list[int] = []

    def columns(table: str) -> set[str]:
        engine.dispose()
        return {column["name"] for column in inspect(engine).get_columns(table)}

    def run(statement, **params):
        engine.dispose()
        with engine.begin() as conn:
            result = conn.execute(text(statement), params)
            if not result.returns_rows:
                return None
            return result.mappings().all()

    try:
        assert "content_sha256" in columns("documents")
        assert "object_version" in columns("documents")
        assert "object_media_type" in columns("documents")
        assert "content_sha256" in columns("export_records")
        assert "content_type" in columns("export_records")

        _alembic("downgrade", PARENT)
        assert "content_sha256" not in columns("documents")
        assert "content_sha256" not in columns("export_records")
        rows = run(
            """
            INSERT INTO documents (workspace_id, storage_key, filename, status)
            VALUES (1, 'raw/1/tc10006-legacy.pdf', 'legacy.pdf', 'uploaded')
            RETURNING id
            """
        )
        document_id = rows[0]["id"]
        created.append(document_id)
        export_rows = run(
            """
            INSERT INTO export_records (workspace_id, storage_key, filename, status)
            VALUES (1, 'exports/1/tc10006-legacy.xlsx', 'legacy.xlsx', 'completed')
            RETURNING id
            """
        )
        export_id = export_rows[0]["id"]

        _alembic("upgrade", REVISION)
        assert "content_sha256" in columns("documents")
        document = run(
            "SELECT filename, content_sha256, object_version, object_media_type "
            "FROM documents WHERE id = :id",
            id=document_id,
        )[0]
        assert document["filename"] == "legacy.pdf"
        assert document["content_sha256"] is None
        assert document["object_version"] is None
        assert document["object_media_type"] is None
        exported = run(
            "SELECT filename, content_sha256, object_version, content_type "
            "FROM export_records WHERE id = :id",
            id=export_id,
        )[0]
        assert exported["filename"] == "legacy.xlsx"
        assert exported["content_sha256"] is None
        assert exported["content_type"] is None

        _alembic("downgrade", PARENT)
        assert "content_sha256" not in columns("documents")
        parked = run(
            "SELECT filename, storage_key FROM documents WHERE id = :id",
            id=document_id,
        )[0]
        assert parked["filename"] == "legacy.pdf"
        assert parked["storage_key"] == "raw/1/tc10006-legacy.pdf"
    finally:
        _alembic("upgrade", "head")
        for document_id in created:
            run("DELETE FROM documents WHERE id = :id", id=document_id)
        run("DELETE FROM export_records WHERE storage_key = 'exports/1/tc10006-legacy.xlsx'")
        engine.dispose()


def test_checksum_downloads_and_legacy_backfill(client, db_session):
    from app.main import app
    from app.services.storage import get_storage
    from app.services.storage_checksum import (
        CHECKSUM_DETAIL,
        BackfillReport,
        backfill_storage_checksums,
        format_report,
    )

    assert CHECKSUM_DETAIL == _DETAIL

    suffix = uuid.uuid4().hex[:12]
    storage = _Store()
    email = f"tc10006-{suffix}@example.com"
    user = User(
        email=email,
        password_hash=hash_password(_LOGIN),
        display_name="Checksum",
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="admin", suspended=False))
    own_digest = _sha(_OWN)
    export_digest = _sha(_EXPORT)
    keys = {
        "document": f"raw/1/{suffix}.pdf",
        "mismatch": f"raw/1/{suffix}-mismatch.pdf",
        "missing": f"raw/1/{suffix}-missing.pdf",
        "plain": f"raw/1/{suffix}-plain.pdf",
        "foreign_key": f"raw/2/{suffix}-foreign-key.pdf",
        "foreign_row": f"raw/2/{suffix}-foreign-row.pdf",
        "legacy_doc": f"raw/1/{suffix}-legacy.pdf",
        "legacy_bad": f"raw/2/{suffix}-legacy-bad.pdf",
        "legacy_gone": f"raw/1/{suffix}-legacy-gone.pdf",
        "export": f"exports/1/{suffix}.xlsx",
        "export_mismatch": f"exports/1/{suffix}-bad.xlsx",
        "export_plain": f"exports/1/{suffix}-plain.xlsx",
        "export_legacy": f"exports/1/{suffix}-legacy.xlsx",
        "export_job_bad": f"exports/1/{suffix}-job.xlsx",
        "export_foreign": f"exports/2/{suffix}-foreign.xlsx",
    }
    storage.put("raw", keys["document"], _OWN, meta=_meta(1, own_digest, 1, _PDF), media=_PDF)
    storage.put("raw", keys["mismatch"], _OWN, meta=_meta(1, own_digest, 1, _PDF), media=_PDF)
    storage.put(
        "raw", keys["foreign_key"], _FOREIGN, meta=_meta(2, _sha(_FOREIGN), 1, _PDF), media=_PDF
    )
    storage.put(
        "raw", keys["foreign_row"], _FOREIGN, meta=_meta(2, _sha(_FOREIGN), 1, _PDF), media=_PDF
    )
    storage.put("raw", keys["legacy_doc"], _OWN, media=_PDF)
    storage.put("raw", keys["legacy_bad"], _FOREIGN, media=_PDF)
    storage.put(
        "exports",
        keys["export"],
        _EXPORT,
        meta=_meta(1, export_digest, 1, XLSX_MEDIA_TYPE),
        media=XLSX_MEDIA_TYPE,
    )
    storage.put(
        "exports",
        keys["export_mismatch"],
        _EXPORT,
        meta=_meta(1, export_digest, 1, XLSX_MEDIA_TYPE),
        media=XLSX_MEDIA_TYPE,
    )
    storage.put("exports", keys["export_legacy"], _EXPORT, media=XLSX_MEDIA_TYPE)
    storage.put("exports", keys["export_job_bad"], _OTHER, media=XLSX_MEDIA_TYPE)
    job = Job(
        workspace_id=1,
        kind="export",
        status="completed",
        result='{"sha256": "%s", "content_type": "%s", "filename": "pack.xlsx"}'
        % (export_digest, XLSX_MEDIA_TYPE),
    )
    bad_job = Job(
        workspace_id=1,
        kind="export",
        status="completed",
        result='{"sha256": "%s", "content_type": "%s", "filename": "pack.xlsx"}'
        % (export_digest, XLSX_MEDIA_TYPE),
    )
    db_session.add_all([job, bad_job])
    db_session.flush()
    rows = {
        "document": Document(
            workspace_id=1,
            storage_key=keys["document"],
            filename="owned.pdf",
            content_type="text/html",
            content_sha256=own_digest,
            object_version=1,
            object_media_type=_PDF,
            status="uploaded",
        ),
        "mismatch": Document(
            workspace_id=1,
            storage_key=keys["mismatch"],
            filename="owned.pdf",
            content_sha256="ab" * 32,
            object_version=1,
            object_media_type=_PDF,
            status="uploaded",
        ),
        "missing": Document(
            workspace_id=1,
            storage_key=keys["missing"],
            filename="owned.pdf",
            content_sha256=own_digest,
            object_version=1,
            object_media_type=_PDF,
            status="uploaded",
        ),
        "plain": Document(
            workspace_id=1,
            storage_key=keys["plain"],
            filename="owned.pdf",
            content_sha256=own_digest,
            object_version=1,
            object_media_type=_PDF,
            status="uploaded",
        ),
        "foreign_key": Document(
            workspace_id=1,
            storage_key=keys["foreign_key"],
            filename="owned.pdf",
            content_sha256=_sha(_FOREIGN),
            object_version=1,
            object_media_type=_PDF,
            status="uploaded",
        ),
        "foreign_row": Document(
            workspace_id=2,
            storage_key=keys["foreign_row"],
            filename="foreign.pdf",
            content_sha256=_sha(_FOREIGN),
            object_version=1,
            object_media_type=_PDF,
            status="uploaded",
        ),
        "legacy_doc": Document(
            workspace_id=1,
            storage_key=keys["legacy_doc"],
            filename="legacy.pdf",
            status="uploaded",
        ),
        "legacy_bad": Document(
            workspace_id=1,
            storage_key=keys["legacy_bad"],
            filename="legacy-bad.pdf",
            status="uploaded",
        ),
        "legacy_gone": Document(
            workspace_id=1,
            storage_key=keys["legacy_gone"],
            filename="gone.pdf",
            status="uploaded",
        ),
    }
    exports = {
        "export": ExportRecord(
            workspace_id=1,
            storage_key=keys["export"],
            filename="pack.xlsx",
            status="completed",
            job_id=job.id,
            content_sha256=export_digest,
            object_version=1,
            content_type=XLSX_MEDIA_TYPE,
        ),
        "export_mismatch": ExportRecord(
            workspace_id=1,
            storage_key=keys["export_mismatch"],
            filename="pack.xlsx",
            status="completed",
            content_sha256="cd" * 32,
            object_version=1,
            content_type=XLSX_MEDIA_TYPE,
        ),
        "export_plain": ExportRecord(
            workspace_id=1,
            storage_key=keys["export_plain"],
            filename="pack.xlsx",
            status="completed",
            content_sha256=export_digest,
            object_version=1,
            content_type=XLSX_MEDIA_TYPE,
        ),
        "export_legacy": ExportRecord(
            workspace_id=1,
            storage_key=keys["export_legacy"],
            filename="legacy.xlsx",
            status="completed",
        ),
        "export_job_bad": ExportRecord(
            workspace_id=1,
            storage_key=keys["export_job_bad"],
            filename="pack.xlsx",
            status="completed",
            job_id=bad_job.id,
        ),
        "export_foreign": ExportRecord(
            workspace_id=2,
            storage_key=keys["export_foreign"],
            filename="foreign.xlsx",
            status="completed",
            content_sha256=export_digest,
            object_version=1,
            content_type=XLSX_MEDIA_TYPE,
        ),
    }
    db_session.add_all([*rows.values(), *exports.values()])
    db_session.commit()
    previous = app.dependency_overrides.get(get_storage)
    app.dependency_overrides[get_storage] = lambda: storage
    signed_in = client.post("/api/auth/login", json={"email": email, "password": _LOGIN})
    assert signed_in.status_code == 200, signed_in.text
    try:
        matched = _document(client, rows["document"].id)
        assert matched.status_code == 200, matched.text
        assert matched.content == _OWN
        assert matched.headers["content-type"].startswith(_PDF)
        assert matched.headers["x-content-sha256"] == own_digest
        _nosniff(matched)
        assert keys["document"] not in matched.text
        exported = _export(client, exports["export"].id)
        assert exported.status_code == 200, exported.text
        assert exported.content == _EXPORT
        assert exported.headers["content-type"].startswith(XLSX_MEDIA_TYPE)
        assert exported.headers["x-content-sha256"] == export_digest
        _nosniff(exported)
        assert keys["export"] not in exported.text

        mismatch = _document(client, rows["mismatch"].id)
        _refused(mismatch, _OWN, keys=[keys["mismatch"], "ab" * 32])
        export_mismatch = _export(client, exports["export_mismatch"].id)
        _refused(export_mismatch, _EXPORT, keys=[keys["export_mismatch"], "cd" * 32])

        before = list(storage.reads)
        missing = _document(client, rows["missing"].id)
        _refused(missing, _OWN, keys=[keys["missing"]])
        assert keys["missing"] in storage.reads
        assert storage.reads[: len(before)] == before

        before = list(storage.reads)
        unhashed = _document(client, rows["legacy_doc"].id)
        _refused(unhashed, _OWN, keys=[keys["legacy_doc"]])
        legacy_export = _export(client, exports["export_legacy"].id)
        _refused(legacy_export, _EXPORT, keys=[keys["export_legacy"]])
        assert storage.reads == before

        before = list(storage.reads)
        crossed = _document(client, rows["foreign_key"].id)
        _refused(crossed, _FOREIGN, keys=[keys["foreign_key"]])
        assert storage.reads == before

        before = list(storage.reads)
        hidden = _document(client, rows["foreign_row"].id)
        foreign_export = _export(client, exports["export_foreign"].id)
        assert hidden.status_code == 404, hidden.text
        assert hidden.json()["detail"] == "Document not found"
        assert foreign_export.status_code == 404, foreign_export.text
        assert foreign_export.json()["detail"] == "Export not found"
        assert _FOREIGN not in hidden.content
        assert keys["foreign_row"] not in hidden.text
        denied = _document(client, rows["foreign_row"].id, workspace_id=2)
        assert denied.status_code == 403, denied.text
        assert storage.reads == before

        client.cookies.clear()
        anonymous = _document(client, rows["document"].id)
        assert anonymous.status_code == 401, anonymous.text
        assert _OWN not in anonymous.content
        signed_in = client.post("/api/auth/login", json={"email": email, "password": _LOGIN})
        assert signed_in.status_code == 200, signed_in.text

        storage.objects[("raw", keys["document"])]["meta"]["version"] = "9"
        version_mismatch = _document(client, rows["document"].id)
        _refused(version_mismatch, _OWN, keys=[keys["document"]])
        storage.objects[("raw", keys["document"])]["meta"]["version"] = "1"
        storage.objects[("raw", keys["document"])]["meta"]["workspace-id"] = "2"
        workspace_meta = _document(client, rows["document"].id)
        _refused(workspace_meta, _OWN, keys=[keys["document"]])
        storage.objects[("raw", keys["document"])]["meta"]["workspace-id"] = "1"
        storage.objects[("raw", keys["document"])]["meta"]["media-type"] = "text/plain"
        type_mismatch = _document(client, rows["document"].id)
        _refused(type_mismatch, _OWN, keys=[keys["document"]])
        storage.objects[("raw", keys["document"])]["meta"] = _meta(1, own_digest, 1, _PDF)
        restored = _document(client, rows["document"].id)
        assert restored.status_code == 200, restored.text
        assert restored.content == _OWN

        job_bad = _export(client, exports["export_job_bad"].id)
        _refused(job_bad, _OTHER, keys=[keys["export_job_bad"]])

        legacy = db_session.get(Document, rows["legacy_doc"].id)
        assert legacy.content_sha256 is None
        dry = backfill_storage_checksums(db_session, storage, execute=False)
        db_session.refresh(legacy)
        assert legacy.content_sha256 is None
        assert dry.pending >= 1
        assert "raw/" not in format_report(dry, execute=False)
        assert own_digest not in format_report(dry, execute=False)
        still = _document(client, rows["legacy_doc"].id)
        _refused(still, _OWN, keys=[keys["legacy_doc"]])

        done = backfill_storage_checksums(db_session, storage, execute=True)
        assert isinstance(done, BackfillReport)
        assert done.updated >= 1
        assert done.disagreed >= 1
        assert done.missing >= 1
        assert done.mismatched >= 1
        db_session.refresh(legacy)
        assert legacy.content_sha256 == own_digest
        assert legacy.object_version == 1
        assert legacy.object_media_type == _PDF
        filled = _document(client, rows["legacy_doc"].id)
        assert filled.status_code == 200, filled.text
        assert filled.content == _OWN
        _nosniff(filled)

        bad = db_session.get(Document, rows["legacy_bad"].id)
        assert bad.content_sha256 is None
        gone = db_session.get(Document, rows["legacy_gone"].id)
        assert gone.content_sha256 is None
        legacy_export_row = db_session.get(ExportRecord, exports["export_legacy"].id)
        assert legacy_export_row.content_sha256 == export_digest
        assert legacy_export_row.object_version == 1
        assert legacy_export_row.content_type == XLSX_MEDIA_TYPE
        streamed = _export(client, exports["export_legacy"].id)
        assert streamed.status_code == 200, streamed.text
        assert streamed.content == _EXPORT
        job_row = db_session.get(ExportRecord, exports["export_job_bad"].id)
        assert job_row.content_sha256 is None

        uploaded = client.post(
            "/api/documents/upload",
            data={"workspace_id": "1"},
            files={"file": ("note.txt", b"synthetic checksum text", "text/html")},
        )
        assert uploaded.status_code == 200, uploaded.text
        uploaded_id = uploaded.json()["id"]
        stored = db_session.get(Document, uploaded_id)
        assert stored.content_sha256 == _sha(b"synthetic checksum text")
        assert stored.object_version == 1
        assert stored.object_media_type == "text/plain; charset=utf-8"
        assert stored.content_type == "text/html"
        preview = _document(client, uploaded_id)
        assert preview.status_code == 200, preview.text
        assert preview.content == b"synthetic checksum text"
        assert preview.headers["content-type"].startswith("text/plain")
        _nosniff(preview)
        rows["uploaded"] = stored
    finally:
        app.dependency_overrides.pop(get_storage, None)
        if previous is not None:
            app.dependency_overrides[get_storage] = previous
        client.cookies.clear()
        db_session.rollback()
        doc_ids = [row.id for row in rows.values()]
        export_ids = [row.id for row in exports.values()]
        db_session.query(ExportRecord).filter(ExportRecord.id.in_(export_ids)).delete(
            synchronize_session=False
        )
        db_session.query(Job).filter(Job.id.in_([job.id, bad_job.id])).delete(
            synchronize_session=False
        )
        db_session.query(Document).filter(Document.id.in_(doc_ids)).delete(
            synchronize_session=False
        )
        db_session.query(Document).filter(
            Document.workspace_id == 1, Document.filename == "note.txt"
        ).delete(synchronize_session=False)
        db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete(
            synchronize_session=False
        )
        db_session.query(UserSession).filter(UserSession.user_id == user.id).delete(
            synchronize_session=False
        )
        db_session.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db_session.commit()


def test_backfill_command_prints_counts_only(client, db_session, capsys):
    from app.services.storage_checksum import main

    suffix = uuid.uuid4().hex[:8]
    storage = _Store()
    key = f"raw/1/{suffix}.pdf"
    storage.put("raw", key, _OWN, media=_PDF)
    row = Document(
        workspace_id=1,
        storage_key=key,
        filename="counts.pdf",
        status="uploaded",
    )
    db_session.add(row)
    db_session.commit()
    holder = {"session": db_session}

    class _Open:
        def __call__(self):
            return self

        def close(self):
            return None

        def __getattr__(self, name):
            return getattr(holder["session"], name)

    opened = _Open()

    def session_local():
        return opened

    def storage_client():
        return storage

    import app.core.database as database
    import app.services.storage as storage_mod

    previous_session = database.SessionLocal
    previous_storage = storage_mod.StorageClient
    database.SessionLocal = session_local
    storage_mod.StorageClient = storage_client
    try:
        assert main([]) == 0
        dry_text = capsys.readouterr().out
        assert "dry-run" in dry_text
        assert key not in dry_text
        assert _sha(_OWN) not in dry_text
        db_session.refresh(row)
        assert row.content_sha256 is None
        assert main(["--execute"]) == 0
        done_text = capsys.readouterr().out
        assert "execute" in done_text
        assert key not in done_text
        assert _sha(_OWN) not in done_text
        db_session.refresh(row)
        assert row.content_sha256 == _sha(_OWN)
    finally:
        database.SessionLocal = previous_session
        storage_mod.StorageClient = previous_storage
        db_session.query(Document).filter(Document.id == row.id).delete(synchronize_session=False)
        db_session.commit()


def test_format_report_has_no_object_details():
    from app.services.storage_checksum import BackfillReport, format_report

    report = BackfillReport(pending=2, updated=0, missing=1, disagreed=1, mismatched=1)
    text_body = format_report(report, execute=False)
    assert text_body == ("dry-run pending=2 updated=0 missing=1 disagreed=1 mismatched=1 already=0")
    assert "/" not in text_body


def _person(db_session, email: str, workspaces: tuple[int, ...] = (1,)):
    user = User(
        email=email,
        password_hash=hash_password(_LOGIN),
        display_name="Checksum follow-up",
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()
    for workspace_id in workspaces:
        db_session.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user.id,
                role="admin",
                suspended=False,
            )
        )
    db_session.commit()
    return user


def _drop_person(db_session, user, documents, exports, jobs):
    db_session.rollback()
    if exports:
        db_session.query(ExportRecord).filter(
            ExportRecord.id.in_([row.id for row in exports])
        ).delete(synchronize_session=False)
    if jobs:
        db_session.query(Job).filter(Job.id.in_([row.id for row in jobs])).delete(
            synchronize_session=False
        )
    if documents:
        db_session.query(Document).filter(Document.id.in_([row.id for row in documents])).delete(
            synchronize_session=False
        )
    db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete(
        synchronize_session=False
    )
    db_session.query(UserSession).filter(UserSession.user_id == user.id).delete(
        synchronize_session=False
    )
    db_session.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db_session.commit()


def _install_store(storage):
    from app.main import app
    from app.services.storage import get_storage

    previous = app.dependency_overrides.get(get_storage)
    app.dependency_overrides[get_storage] = lambda: storage
    return app, previous


def _remove_store(app, previous) -> None:
    from app.services.storage import get_storage

    app.dependency_overrides.pop(get_storage, None)
    if previous is not None:
        app.dependency_overrides[get_storage] = previous


def test_backfill_skips_agreeing_versioned_rows(client, db_session):
    """A correct hash at version 2 or higher is already complete.

    Dry-run does not count it as pending. Execute does not rewrite the object
    or reset the version. A hash that does not match, and a key that names
    another workspace, stay refused.
    """
    from app.services.storage_checksum import backfill_storage_checksums

    suffix = uuid.uuid4().hex[:12]
    storage = _Store()
    email = f"tc10006c-agree-{suffix}@example.com"
    user = _person(db_session, email)
    own_digest = _sha(_OWN)
    export_digest = _sha(_EXPORT)
    foreign_digest = _sha(_FOREIGN)
    keys = {
        "document": f"raw/1/{suffix}-v2.pdf",
        "export": f"exports/1/{suffix}-v3.xlsx",
        "mismatch": f"raw/1/{suffix}-mismatch.pdf",
        "foreign": f"raw/2/{suffix}-foreign.pdf",
    }
    storage.put("raw", keys["document"], _OWN, meta=_meta(1, own_digest, 2, _PDF), media=_PDF)
    storage.put(
        "exports",
        keys["export"],
        _EXPORT,
        meta=_meta(1, export_digest, 3, XLSX_MEDIA_TYPE),
        media=XLSX_MEDIA_TYPE,
    )
    storage.put("raw", keys["mismatch"], _OWN, meta=_meta(1, own_digest, 4, _PDF), media=_PDF)
    storage.put(
        "raw", keys["foreign"], _FOREIGN, meta=_meta(2, foreign_digest, 2, _PDF), media=_PDF
    )
    stamps = {
        name: storage.objects[("raw" if name != "export" else "exports", key)]
        for name, key in keys.items()
    }
    baseline = backfill_storage_checksums(db_session, storage, execute=False)
    job = Job(
        workspace_id=1,
        kind="export",
        status="completed",
        result=json.dumps(
            {"sha256": export_digest, "content_type": XLSX_MEDIA_TYPE, "filename": "rerender.xlsx"}
        ),
    )
    db_session.add(job)
    db_session.flush()
    document = Document(
        workspace_id=1,
        storage_key=keys["document"],
        filename="rerender.pdf",
        content_type="text/html",
        content_sha256=own_digest,
        object_version=2,
        object_media_type=_PDF,
        status="uploaded",
    )
    mismatch = Document(
        workspace_id=1,
        storage_key=keys["mismatch"],
        filename="rerender.pdf",
        content_sha256="ab" * 32,
        object_version=4,
        object_media_type=_PDF,
        status="uploaded",
    )
    foreign = Document(
        workspace_id=1,
        storage_key=keys["foreign"],
        filename="rerender.pdf",
        content_sha256=foreign_digest,
        object_version=2,
        object_media_type=_PDF,
        status="uploaded",
    )
    exported = ExportRecord(
        workspace_id=1,
        storage_key=keys["export"],
        filename="rerender.xlsx",
        status="completed",
        job_id=job.id,
        content_sha256=export_digest,
        object_version=3,
        content_type=XLSX_MEDIA_TYPE,
    )
    db_session.add_all([document, mismatch, foreign, exported])
    db_session.commit()
    app, previous = _install_store(storage)
    signed_in = client.post("/api/auth/login", json={"email": email, "password": _LOGIN})
    assert signed_in.status_code == 200, signed_in.text
    try:
        counted = backfill_storage_checksums(db_session, storage, execute=False)
        assert counted.pending - baseline.pending == 0
        assert counted.mismatched - baseline.mismatched == 1
        assert counted.disagreed - baseline.disagreed == 1
        assert counted.missing - baseline.missing == 0
        assert counted.updated == 0
        assert counted.already - baseline.already == 2
        db_session.refresh(document)
        db_session.refresh(exported)
        assert document.content_sha256 == own_digest
        assert exported.content_sha256 == export_digest

        done = backfill_storage_checksums(db_session, storage, execute=True)
        db_session.refresh(document)
        db_session.refresh(exported)
        db_session.refresh(mismatch)
        db_session.refresh(foreign)
        assert (document.object_version, exported.object_version) == (2, 3)
        assert document.object_media_type == _PDF
        assert document.content_type == "text/html"
        assert exported.content_type == XLSX_MEDIA_TYPE
        assert storage.objects[("raw", keys["document"])] is stamps["document"]
        assert storage.objects[("exports", keys["export"])] is stamps["export"]
        assert storage.objects[("raw", keys["document"])]["meta"]["version"] == "2"
        assert storage.objects[("exports", keys["export"])]["meta"]["version"] == "3"
        assert mismatch.object_version == 4
        assert mismatch.content_sha256 == "ab" * 32
        assert storage.objects[("raw", keys["mismatch"])] is stamps["mismatch"]
        assert foreign.object_version == 2
        assert foreign.content_sha256 == foreign_digest
        assert foreign.storage_key == keys["foreign"]
        assert storage.objects[("raw", keys["foreign"])] is stamps["foreign"]
        assert done.updated == 0

        matched = _document(client, document.id)
        assert matched.status_code == 200, matched.text
        assert matched.content == _OWN
        assert matched.headers["x-content-sha256"] == own_digest
        _nosniff(matched)
        streamed = _export(client, exported.id)
        assert streamed.status_code == 200, streamed.text
        assert streamed.content == _EXPORT
        assert streamed.headers["x-content-sha256"] == export_digest
        _nosniff(streamed)
        _refused(_document(client, mismatch.id), _OWN, keys=[keys["mismatch"], "ab" * 32])
        before_reads = list(storage.reads)
        _refused(_document(client, foreign.id), _FOREIGN, keys=[keys["foreign"], foreign_digest])
        assert storage.reads == before_reads
    finally:
        _remove_store(app, previous)
        client.cookies.clear()
        _drop_person(db_session, user, [document, mismatch, foreign], [exported], [job])


def test_backfill_rerun_after_interrupted_stamp_keeps_versions(client, db_session):
    """Object stamped, row not committed: run the backfill again.

    The null row picks up version 1 from the stamp. A document at version 2
    and an export at version 3 that already agree are not reset and their
    objects are not replaced. A second run changes none of the three.
    """
    from app.services.storage_checksum import backfill_storage_checksums

    suffix = uuid.uuid4().hex[:12]
    storage = _Store()
    email = f"tc10006c-rerun-{suffix}@example.com"
    user = _person(db_session, email)
    own_digest = _sha(_OWN)
    export_digest = _sha(_EXPORT)
    legacy_body = b"%PDF-1.4 synthetic interrupted document"
    legacy_digest = _sha(legacy_body)
    keys = {
        "legacy": f"raw/1/{suffix}-interrupted.pdf",
        "document": f"raw/1/{suffix}-kept.pdf",
        "export": f"exports/1/{suffix}-kept.xlsx",
    }
    storage.put(
        "raw", keys["legacy"], legacy_body, meta=_meta(1, legacy_digest, 1, _PDF), media=_PDF
    )
    storage.put("raw", keys["document"], _OWN, meta=_meta(1, own_digest, 2, _PDF), media=_PDF)
    storage.put(
        "exports",
        keys["export"],
        _EXPORT,
        meta=_meta(1, export_digest, 3, XLSX_MEDIA_TYPE),
        media=XLSX_MEDIA_TYPE,
    )
    kept = {
        "document": storage.objects[("raw", keys["document"])],
        "export": storage.objects[("exports", keys["export"])],
    }
    job = Job(
        workspace_id=1,
        kind="export",
        status="completed",
        result=json.dumps(
            {"sha256": export_digest, "content_type": XLSX_MEDIA_TYPE, "filename": "kept.xlsx"}
        ),
    )
    db_session.add(job)
    db_session.flush()
    legacy = Document(
        workspace_id=1,
        storage_key=keys["legacy"],
        filename="interrupted.pdf",
        status="uploaded",
    )
    document = Document(
        workspace_id=1,
        storage_key=keys["document"],
        filename="kept.pdf",
        content_type="text/html",
        content_sha256=own_digest,
        object_version=2,
        object_media_type=_PDF,
        status="uploaded",
    )
    exported = ExportRecord(
        workspace_id=1,
        storage_key=keys["export"],
        filename="kept.xlsx",
        status="completed",
        job_id=job.id,
        content_sha256=export_digest,
        object_version=3,
        content_type=XLSX_MEDIA_TYPE,
    )
    db_session.add_all([legacy, document, exported])
    db_session.commit()
    app, previous = _install_store(storage)
    signed_in = client.post("/api/auth/login", json={"email": email, "password": _LOGIN})
    assert signed_in.status_code == 200, signed_in.text
    try:
        refused = _document(client, legacy.id)
        _refused(refused, legacy_body, keys=[keys["legacy"], legacy_digest])
        held = _document(client, document.id)
        assert held.status_code == 200, held.text
        assert held.content == _OWN
        held_export = _export(client, exported.id)
        assert held_export.status_code == 200, held_export.text
        assert held_export.content == _EXPORT

        dry = backfill_storage_checksums(db_session, storage, execute=False)
        db_session.refresh(legacy)
        db_session.refresh(document)
        db_session.refresh(exported)
        assert legacy.content_sha256 is None
        assert legacy.object_version is None
        assert (document.object_version, exported.object_version) == (2, 3)
        assert storage.objects[("raw", keys["document"])] is kept["document"]
        assert storage.objects[("exports", keys["export"])] is kept["export"]
        assert dry.updated == 0

        backfill_storage_checksums(db_session, storage, execute=True)
        db_session.refresh(legacy)
        db_session.refresh(document)
        db_session.refresh(exported)
        assert (
            legacy.object_version,
            document.object_version,
            exported.object_version,
        ) == (1, 2, 3)
        assert legacy.content_sha256 == legacy_digest
        assert legacy.object_media_type == _PDF
        assert document.content_sha256 == own_digest
        assert exported.content_sha256 == export_digest
        assert storage.objects[("raw", keys["document"])] is kept["document"]
        assert storage.objects[("exports", keys["export"])] is kept["export"]
        assert storage.objects[("raw", keys["document"])]["meta"]["version"] == "2"
        assert storage.objects[("exports", keys["export"])]["meta"]["version"] == "3"
        filled = _document(client, legacy.id)
        assert filled.status_code == 200, filled.text
        assert filled.content == legacy_body
        assert filled.headers["x-content-sha256"] == legacy_digest
        _nosniff(filled)
        again_doc = _document(client, document.id)
        assert again_doc.status_code == 200, again_doc.text
        assert again_doc.content == _OWN
        again_export = _export(client, exported.id)
        assert again_export.status_code == 200, again_export.text
        assert again_export.content == _EXPORT

        settled = {
            "legacy": storage.objects[("raw", keys["legacy"])],
            "document": storage.objects[("raw", keys["document"])],
            "export": storage.objects[("exports", keys["export"])],
        }
        second = backfill_storage_checksums(db_session, storage, execute=True)
        db_session.refresh(legacy)
        db_session.refresh(document)
        db_session.refresh(exported)
        assert (
            legacy.object_version,
            document.object_version,
            exported.object_version,
        ) == (1, 2, 3)
        assert storage.objects[("raw", keys["legacy"])] is settled["legacy"]
        assert storage.objects[("raw", keys["document"])] is settled["document"]
        assert storage.objects[("exports", keys["export"])] is settled["export"]
        assert storage.objects[("raw", keys["legacy"])]["meta"]["version"] == "1"
        assert second.updated == 0
    finally:
        _remove_store(app, previous)
        client.cookies.clear()
        _drop_person(db_session, user, [legacy, document], [exported], [job])


def test_moved_document_is_disagreed_and_download_stays_refused(client, db_session):
    """Moving a document keeps the old key. Download stays 409. Backfill counts disagreed."""
    from app.services.storage_checksum import backfill_storage_checksums
    from app.services.workspace_integrity import reassign_parent_workspace

    suffix = uuid.uuid4().hex[:12]
    storage = _Store()
    email = f"tc10006c-moved-{suffix}@example.com"
    user = _person(db_session, email, (1, 2))
    digest = _sha(_OWN)
    key = f"raw/1/{suffix}-moved.pdf"
    storage.put("raw", key, _OWN, meta=_meta(1, digest, 2, _PDF), media=_PDF)
    stamp = storage.objects[("raw", key)]
    baseline = backfill_storage_checksums(db_session, storage, execute=False)
    row = Document(
        workspace_id=1,
        storage_key=key,
        filename="moved.pdf",
        content_type="text/html",
        content_sha256=digest,
        object_version=2,
        object_media_type=_PDF,
        status="uploaded",
    )
    db_session.add(row)
    db_session.commit()
    reassign_parent_workspace(db_session, row, workspace_id=2)
    db_session.commit()
    db_session.refresh(row)
    app, previous = _install_store(storage)
    signed_in = client.post("/api/auth/login", json={"email": email, "password": _LOGIN})
    assert signed_in.status_code == 200, signed_in.text
    try:
        assert row.workspace_id == 2
        assert row.storage_key == key
        counted = backfill_storage_checksums(db_session, storage, execute=False)
        assert counted.disagreed == baseline.disagreed + 1
        assert counted.pending == baseline.pending
        assert counted.mismatched == baseline.mismatched
        assert counted.missing == baseline.missing
        assert counted.updated == baseline.updated
        assert getattr(counted, "already", 0) == getattr(baseline, "already", 0)
        db_session.refresh(row)
        assert row.content_sha256 == digest
        assert row.object_version == 2
        assert storage.objects[("raw", key)] is stamp

        hidden = _document(client, row.id, workspace_id=1)
        assert hidden.status_code == 404, hidden.text
        assert _OWN not in hidden.content
        assert key not in hidden.text
        switched = client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
        assert switched.status_code == 200, switched.text
        before_reads = list(storage.reads)
        refused = _document(client, row.id, workspace_id=2)
        _refused(refused, _OWN, keys=[key, digest])
        assert storage.reads == before_reads

        done = backfill_storage_checksums(db_session, storage, execute=True)
        db_session.refresh(row)
        assert row.workspace_id == 2
        assert row.storage_key == key
        assert row.content_sha256 == digest
        assert row.object_version == 2
        assert row.object_media_type == _PDF
        assert storage.objects[("raw", key)] is stamp
        assert done.updated == 0
        before_reads = list(storage.reads)
        again = _document(client, row.id, workspace_id=2)
        _refused(again, _OWN, keys=[key, digest])
        assert storage.reads == before_reads
        assert again.status_code == 409
    finally:
        _remove_store(app, previous)
        client.cookies.clear()
        _drop_person(db_session, user, [row], [], [])
