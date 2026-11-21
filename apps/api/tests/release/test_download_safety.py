"""TC-07-008 download safety on PostgreSQL.

Document, export, and trust-request attachment bytes require a current
workspace session. An expired session and a revoked workspace session are
401. A cross-workspace id is 404. A stored key that fails validation is
refused before any storage read. An archived document is not streamed.
Object buckets are private, and production must be able to prove that.

This file is not skipped. CI runs it with TC_REQUIRE_DB=1.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError

from app.core.password import hash_password
from app.models import (
    Document,
    ExportRecord,
    Job,
    TrustRequest,
    User,
    UserSession,
    WorkspaceMember,
)
from app.services.export_service import XLSX_MEDIA_TYPE
from app.services.storage import BucketNotPrivate, PrivacyAttestationRejected, StorageClient

_REAL_ENSURE = StorageClient.ensure_buckets

_OWN_PDF = b"%PDF-1.4 synthetic owned document"
_OWN_EXPORT = b"PK\x03\x04 synthetic hashed export"
_OWN_LEGACY = b"PK\x03\x04 synthetic legacy export"
_OWN_ATTACHMENT = b"synthetic attachment bytes"
_FOREIGN_PDF = b"FOREIGN-DOCUMENT-BYTES"
_FOREIGN_EXPORT = b"FOREIGN-EXPORT-BYTES"
_FOREIGN_ATTACHMENT = b"FOREIGN-ATTACHMENT-BYTES"
_LOGIN_PHRASE = "synthetic-download-07008"
_NOSNIFF = "nosniff"
_BAD_KEYS = ("../owned.pdf", "/owned.pdf", "raw/1/../owned.pdf")


class _MemoryStorage:
    def __init__(self) -> None:
        self.bucket_raw = "raw"
        self.bucket_exports = "exports"
        self.objects: dict[tuple[str, str], bytes] = {}
        self.reads: list[str] = []

    def put(self, bucket: str, key: str, body: bytes) -> None:
        self.objects[(bucket, key)] = body

    def download(self, bucket: str, key: str) -> bytes:
        self.reads.append(key)
        body = self.objects.get((bucket, key))
        if body is None:
            raise FileNotFoundError(key)
        return body

    def download_stream(self, bucket: str, key: str):
        self.reads.append(key)
        body = self.objects.get((bucket, key))
        if body is None:
            raise FileNotFoundError(key)
        return iter([body])

    def exists(self, bucket: str, key: str) -> bool:
        self.reads.append(key)
        return (bucket, key) in self.objects


class _Buckets:
    """In-memory bucket metadata. Object reads are a failure."""

    def __init__(self) -> None:
        self.buckets: dict[str, dict] = {}
        self.calls: list[str] = []
        self.block_unsupported = False

    def add(self, name: str, *, public_acl: bool = False, public_policy: bool = False, block=None):
        self.buckets[name] = {
            "public_acl": public_acl,
            "public_policy": public_policy,
            "block": block,
        }

    def head_bucket(self, Bucket: str):
        self.calls.append("head_bucket")
        if Bucket not in self.buckets:
            raise _client_error("404", "HeadBucket")

    def create_bucket(self, Bucket: str):
        self.calls.append("create_bucket")
        self.buckets[Bucket] = {"public_acl": False, "public_policy": False, "block": None}

    def put_bucket_acl(self, Bucket: str, ACL: str):
        self.calls.append("put_bucket_acl")
        self.buckets[Bucket]["public_acl"] = ACL != "private"

    def put_public_access_block(self, Bucket: str, PublicAccessBlockConfiguration: dict):
        self.calls.append("put_public_access_block")
        if self.block_unsupported:
            raise _client_error("NotImplemented", "PutPublicAccessBlock")
        flags = (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        )
        self.buckets[Bucket]["block"] = all(
            PublicAccessBlockConfiguration.get(flag) is True for flag in flags
        )

    def get_bucket_acl(self, Bucket: str):
        self.calls.append("get_bucket_acl")
        if self.buckets[Bucket]["public_acl"]:
            grant = {
                "Grantee": {
                    "Type": "Group",
                    "URI": "http://acs.amazonaws.com/groups/global/AllUsers",
                },
                "Permission": "READ",
            }
        else:
            grant = {
                "Grantee": {"Type": "CanonicalUser", "ID": "owner"},
                "Permission": "FULL_CONTROL",
            }
        return {"Grants": [grant]}

    def get_bucket_policy(self, Bucket: str):
        self.calls.append("get_bucket_policy")
        if not self.buckets[Bucket]["public_policy"]:
            raise _client_error("NoSuchBucketPolicy", "GetBucketPolicy")
        return {
            "Policy": json.dumps(
                {
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": "s3:GetObject",
                            "Resource": f"arn:aws:s3:::{Bucket}/*",
                        }
                    ]
                }
            )
        }

    def get_public_access_block(self, Bucket: str):
        self.calls.append("get_public_access_block")
        if self.block_unsupported:
            raise _client_error("NotImplemented", "GetPublicAccessBlock")
        block = self.buckets[Bucket]["block"]
        if block is None:
            raise _client_error("NoSuchPublicAccessBlockConfiguration", "GetPublicAccessBlock")
        flag = bool(block)
        return {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": flag,
                "IgnorePublicAcls": flag,
                "BlockPublicPolicy": flag,
                "RestrictPublicBuckets": flag,
            }
        }

    def get_object(self, **kwargs):
        raise AssertionError("object read during bucket check")


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


def _storage_client(fake: _Buckets) -> StorageClient:
    client = StorageClient()
    client._client = fake
    client._bucket_raw = "raw-bucket"
    client._bucket_exports = "export-bucket"
    return client


def _use_real_ensure(monkeypatch) -> None:
    monkeypatch.setattr(StorageClient, "ensure_buckets", _REAL_ENSURE)


@pytest.fixture
def downloads(client, db_session):
    from app.main import app
    from app.services.storage import get_storage

    suffix = uuid.uuid4().hex[:12]
    storage = _MemoryStorage()
    email = f"tc07008-{suffix}@example.com"
    user = User(
        email=email,
        password_hash=hash_password(_LOGIN_PHRASE),
        display_name="Download safety",
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="admin", suspended=False))
    keys = {
        "document": f"raw/1/{suffix}.pdf",
        "export": f"exports/1/{suffix}.xlsx",
        "legacy": f"exports/1/{suffix}-legacy.xlsx",
        "attachment": f"trust-requests/1/{suffix}.txt",
        "foreign_document": f"raw/2/{suffix}-foreign.pdf",
        "foreign_export": f"exports/2/{suffix}-foreign.xlsx",
        "foreign_attachment": f"trust-requests/2/{suffix}-foreign.txt",
    }
    storage.put("raw", keys["document"], _OWN_PDF)
    storage.put("exports", keys["export"], _OWN_EXPORT)
    storage.put("exports", keys["legacy"], _OWN_LEGACY)
    storage.put("raw", keys["attachment"], _OWN_ATTACHMENT)
    storage.put("raw", keys["foreign_document"], _FOREIGN_PDF)
    storage.put("exports", keys["foreign_export"], _FOREIGN_EXPORT)
    storage.put("raw", keys["foreign_attachment"], _FOREIGN_ATTACHMENT)
    digest = hashlib.sha256(_OWN_EXPORT).hexdigest()
    job = Job(
        workspace_id=1,
        kind="export",
        status="completed",
        result=json.dumps(
            {"sha256": digest, "content_type": XLSX_MEDIA_TYPE, "filename": "pack.xlsx"}
        ),
    )
    db_session.add(job)
    db_session.flush()
    document = Document(
        workspace_id=1,
        storage_key=keys["document"],
        filename="owned.pdf",
        content_type="text/html",
        status="uploaded",
    )
    foreign_document = Document(
        workspace_id=2,
        storage_key=keys["foreign_document"],
        filename="foreign.pdf",
        content_type="text/html",
        status="uploaded",
    )
    export = ExportRecord(
        workspace_id=1,
        storage_key=keys["export"],
        filename="pack.xlsx",
        status="completed",
        job_id=job.id,
    )
    legacy = ExportRecord(
        workspace_id=1,
        storage_key=keys["legacy"],
        filename="legacy.xlsx",
        status="completed",
    )
    foreign_export = ExportRecord(
        workspace_id=2,
        storage_key=keys["foreign_export"],
        filename="foreign.xlsx",
        status="completed",
    )
    attachment = TrustRequest(
        workspace_id=1,
        requester_email=f"{suffix}@example.com",
        message="Synthetic request",
        status="new",
        attachment_filename="note.txt",
        attachment_storage_key=keys["attachment"],
        attachment_size=len(_OWN_ATTACHMENT),
    )
    foreign_attachment = TrustRequest(
        workspace_id=2,
        requester_email=f"{suffix}-foreign@example.com",
        message="Synthetic foreign request",
        status="new",
        attachment_filename="foreign.txt",
        attachment_storage_key=keys["foreign_attachment"],
        attachment_size=len(_FOREIGN_ATTACHMENT),
    )
    db_session.add_all(
        [
            document,
            foreign_document,
            export,
            legacy,
            foreign_export,
            attachment,
            foreign_attachment,
        ]
    )
    db_session.commit()
    previous = app.dependency_overrides.get(get_storage)
    app.dependency_overrides[get_storage] = lambda: storage
    signed_in = client.post("/api/auth/login", json={"email": email, "password": _LOGIN_PHRASE})
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json().get("workspace_id") == 1
    state = {
        "client": client,
        "db": db_session,
        "storage": storage,
        "user_id": user.id,
        "keys": keys,
        "document_id": document.id,
        "export_id": export.id,
        "legacy_id": legacy.id,
        "attachment_id": attachment.id,
        "foreign_document_id": foreign_document.id,
        "foreign_export_id": foreign_export.id,
        "foreign_attachment_id": foreign_attachment.id,
        "job_id": job.id,
        "secret": _FOREIGN_PDF + _FOREIGN_EXPORT + _FOREIGN_ATTACHMENT + _OWN_PDF,
    }
    try:
        yield state
    finally:
        app.dependency_overrides.pop(get_storage, None)
        if previous is not None:
            app.dependency_overrides[get_storage] = previous
        client.cookies.clear()
        db_session.rollback()
        db_session.query(ExportRecord).filter(
            ExportRecord.id.in_([export.id, legacy.id, foreign_export.id])
        ).delete(synchronize_session=False)
        db_session.query(Job).filter(Job.id == job.id).delete(synchronize_session=False)
        db_session.query(Document).filter(
            Document.id.in_([document.id, foreign_document.id])
        ).delete(synchronize_session=False)
        db_session.query(TrustRequest).filter(
            TrustRequest.id.in_([attachment.id, foreign_attachment.id])
        ).delete(synchronize_session=False)
        db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete(
            synchronize_session=False
        )
        db_session.query(UserSession).filter(UserSession.user_id == user.id).delete(
            synchronize_session=False
        )
        db_session.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db_session.commit()


def _document(state, document_id, workspace_id=1):
    return state["client"].get(
        f"/api/documents/{document_id}/content",
        params={"workspace_id": workspace_id},
    )


def _export(state, record_id, workspace_id=1):
    return state["client"].get(
        f"/api/exports/records/{record_id}/download",
        params={"workspace_id": workspace_id},
    )


def _attachment(state, request_id):
    return state["client"].get(f"/api/trust-requests/{request_id}/attachment")


def _owned_responses(state):
    return (
        _document(state, state["document_id"]),
        _export(state, state["export_id"]),
        _export(state, state["legacy_id"]),
        _attachment(state, state["attachment_id"]),
    )


def _assert_no_leak(response, state, *extra: bytes):
    body = response.content
    for secret in (
        _FOREIGN_PDF,
        _FOREIGN_EXPORT,
        _FOREIGN_ATTACHMENT,
        _OWN_PDF,
        _OWN_EXPORT,
        _OWN_LEGACY,
        _OWN_ATTACHMENT,
        *extra,
    ):
        if secret == body and response.status_code == 200:
            continue
        assert secret not in body
    text = response.text
    for key in state["keys"].values():
        assert key not in text
    assert "X-Amz-" not in text
    assert "x-amz-" not in text.lower()


def _assert_nosniff(response):
    assert response.headers["x-content-type-options"] == _NOSNIFF


def test_owned_downloads_set_nosniff_and_hide_the_object_key(downloads):
    document, exported, legacy, attachment = _owned_responses(downloads)
    assert document.status_code == 200, document.text
    assert document.content == _OWN_PDF
    assert document.headers["content-type"].startswith("application/pdf")
    assert document.headers["content-disposition"].startswith("inline;")
    _assert_nosniff(document)
    assert exported.status_code == 200, exported.text
    assert exported.content == _OWN_EXPORT
    assert exported.headers["content-type"].startswith(XLSX_MEDIA_TYPE)
    assert "pack.xlsx" in exported.headers["content-disposition"]
    _assert_nosniff(exported)
    assert legacy.status_code == 200, legacy.text
    assert legacy.content == _OWN_LEGACY
    assert "legacy.xlsx" in legacy.headers["content-disposition"]
    _assert_nosniff(legacy)
    assert attachment.status_code == 200, attachment.text
    assert attachment.content == _OWN_ATTACHMENT
    assert attachment.headers["content-type"].startswith("application/octet-stream")
    assert 'filename="note.txt"' in attachment.headers["content-disposition"]
    _assert_nosniff(attachment)
    for response in (document, exported, legacy, attachment):
        assert "\r" not in response.headers["content-disposition"]
        assert "\n" not in response.headers["content-disposition"]
        assert "X-Amz-" not in response.text
    assert downloads["keys"]["foreign_document"] not in downloads["storage"].reads
    assert downloads["keys"]["foreign_export"] not in downloads["storage"].reads
    assert downloads["keys"]["foreign_attachment"] not in downloads["storage"].reads


def test_expired_session_is_unauthorized_on_each_download(downloads):
    row = downloads["db"].query(UserSession).filter_by(user_id=downloads["user_id"]).one()
    row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
    downloads["db"].commit()
    before = list(downloads["storage"].reads)
    for response in _owned_responses(downloads):
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Session expired"
        _assert_no_leak(response, downloads)
    assert downloads["storage"].reads == before


def test_revoked_workspace_session_is_unauthorized_on_each_download(downloads):
    member = (
        downloads["db"]
        .query(WorkspaceMember)
        .filter_by(user_id=downloads["user_id"], workspace_id=1)
        .one()
    )
    member.sessions_revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    downloads["db"].commit()
    before = list(downloads["storage"].reads)
    for response in _owned_responses(downloads):
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Session invalidated"
        _assert_no_leak(response, downloads)
    assert downloads["storage"].reads == before


def test_cross_workspace_id_is_not_found_and_leaks_nothing(downloads):
    before = list(downloads["storage"].reads)
    document = _document(downloads, downloads["foreign_document_id"])
    exported = _export(downloads, downloads["foreign_export_id"])
    attachment = _attachment(downloads, downloads["foreign_attachment_id"])
    denied_document = _document(downloads, downloads["foreign_document_id"], workspace_id=2)
    denied_export = _export(downloads, downloads["foreign_export_id"], workspace_id=2)
    for response, detail in (
        (document, "Document not found"),
        (exported, "Export not found"),
        (attachment, "Trust request not found"),
    ):
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == detail
        _assert_no_leak(response, downloads)
    for response in (denied_document, denied_export):
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == "Access denied"
        _assert_no_leak(response, downloads)
    assert downloads["storage"].reads == before


def test_invalid_stored_key_is_refused_before_a_storage_read(downloads):
    db = downloads["db"]
    document = db.get(Document, downloads["document_id"])
    exported = db.get(ExportRecord, downloads["export_id"])
    legacy = db.get(ExportRecord, downloads["legacy_id"])
    attachment = db.get(TrustRequest, downloads["attachment_id"])
    originals = (
        document.storage_key,
        exported.storage_key,
        legacy.storage_key,
        attachment.attachment_storage_key,
    )
    rows = (document, exported, legacy, attachment)
    fetchers = (
        lambda: _document(downloads, downloads["document_id"]),
        lambda: _export(downloads, downloads["export_id"]),
        lambda: _export(downloads, downloads["legacy_id"]),
        lambda: _attachment(downloads, downloads["attachment_id"]),
    )
    for bad in _BAD_KEYS:
        for row, fetcher in zip(rows, fetchers, strict=True):
            if isinstance(row, TrustRequest):
                row.attachment_storage_key = bad
            else:
                row.storage_key = bad
            db.commit()
            before = list(downloads["storage"].reads)
            response = fetcher()
            assert response.status_code == 400, response.text
            assert response.json()["detail"] == "Invalid storage key"
            _assert_nosniff(response)
            assert bad not in response.text
            _assert_no_leak(response, downloads, bad.encode())
            assert downloads["storage"].reads == before
    rows[0].storage_key = originals[0]
    rows[1].storage_key = originals[1]
    rows[2].storage_key = originals[2]
    rows[3].attachment_storage_key = originals[3]
    db.commit()


def test_archived_document_is_not_streamed(downloads):
    row = downloads["db"].get(Document, downloads["document_id"])
    row.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    downloads["db"].commit()
    before = list(downloads["storage"].reads)
    response = _document(downloads, downloads["document_id"])
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Document not found"
    _assert_no_leak(response, downloads)
    assert downloads["storage"].reads == before
    listed = downloads["client"].get(
        "/api/documents",
        params={"workspace_id": 1, "archived": "only", "page": 1, "page_size": 50},
    )
    assert listed.status_code == 200, listed.text
    match = [item for item in listed.json()["items"] if item["id"] == downloads["document_id"]]
    assert len(match) == 1
    assert match[0]["source_preview_url"] is None
    assert match[0]["source_eligibility"] == "ineligible"
    assert downloads["keys"]["document"] not in listed.text
    assert downloads["storage"].reads == before


def test_existing_public_bucket_is_refused(monkeypatch):
    _use_real_ensure(monkeypatch)
    public_acl = _Buckets()
    public_acl.add("raw-bucket", public_acl=True)
    public_acl.add("export-bucket")
    with pytest.raises(BucketNotPrivate, match="not private"):
        _storage_client(public_acl).ensure_buckets()
    assert "get_object" not in public_acl.calls

    public_policy = _Buckets()
    public_policy.add("raw-bucket", public_policy=True)
    public_policy.add("export-bucket")
    with pytest.raises(BucketNotPrivate, match="not private"):
        _storage_client(public_policy).ensure_buckets()
    assert "get_object" not in public_policy.calls


def test_production_bucket_must_prove_it_is_private(monkeypatch):
    _use_real_ensure(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    missing_block = _Buckets()
    missing_block.add("raw-bucket")
    missing_block.add("export-bucket")
    with pytest.raises(BucketNotPrivate, match="not private"):
        _storage_client(missing_block).ensure_buckets()

    unsupported = _Buckets()
    unsupported.block_unsupported = True
    unsupported.add("raw-bucket")
    unsupported.add("export-bucket")
    with pytest.raises(BucketNotPrivate, match="could not be confirmed"):
        _storage_client(unsupported).ensure_buckets()

    private = _Buckets()
    private.add("raw-bucket", block=True)
    private.add("export-bucket", block=True)
    _storage_client(private).ensure_buckets()
    assert "get_object" not in private.calls
    assert "put_bucket_acl" not in private.calls


def test_new_bucket_is_created_private_and_startup_does_not_hide_it(monkeypatch, caplog):
    _use_real_ensure(monkeypatch)
    created = _Buckets()
    _storage_client(created).ensure_buckets()
    assert created.calls.count("create_bucket") == 2
    assert created.calls.count("put_bucket_acl") == 2
    assert created.calls.count("put_public_access_block") == 2
    assert created.buckets["raw-bucket"]["public_acl"] is False
    assert created.buckets["raw-bucket"]["block"] is True
    assert created.buckets["export-bucket"]["block"] is True
    assert "get_object" not in created.calls

    from app.main import _init_object_storage

    def public(self):
        raise BucketNotPrivate("Object storage bucket is not private")

    monkeypatch.setattr(StorageClient, "ensure_buckets", public)
    with pytest.raises(BucketNotPrivate, match="not private"):
        _init_object_storage()

    def down(self):
        raise RuntimeError("synthetic storage down")

    monkeypatch.setattr(StorageClient, "ensure_buckets", down)
    with caplog.at_level(logging.WARNING):
        _init_object_storage()
    assert "bucket init skipped or failed" in caplog.text
    assert "synthetic storage down" in caplog.text


def test_development_bucket_without_a_block_api_can_stay_private(monkeypatch):
    _use_real_ensure(monkeypatch)
    buckets = _Buckets()
    buckets.block_unsupported = True
    buckets.add("raw-bucket")
    buckets.add("export-bucket")
    _storage_client(buckets).ensure_buckets()
    assert "get_object" not in buckets.calls


def _production_store(monkeypatch, *, attestation: str | None, public_policy: bool = False):
    _use_real_ensure(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    if attestation is None:
        monkeypatch.delenv("S3_PRIVACY_ATTESTATION", raising=False)
    else:
        monkeypatch.setenv("S3_PRIVACY_ATTESTATION", attestation)
    buckets = _Buckets()
    buckets.block_unsupported = True
    buckets.add("raw-bucket", public_policy=public_policy)
    buckets.add("export-bucket", public_policy=public_policy)
    return buckets


def test_production_unsupported_block_without_attestation_is_refused(monkeypatch):
    buckets = _production_store(monkeypatch, attestation=None)
    with pytest.raises(BucketNotPrivate, match="could not be confirmed"):
        _storage_client(buckets).ensure_buckets()


def test_production_unsupported_block_with_attestation_starts(monkeypatch, caplog):
    buckets = _production_store(monkeypatch, attestation="unsupported-store-private")
    with caplog.at_level(logging.WARNING, logger="app.services.storage"):
        _storage_client(buckets).ensure_buckets()
    text = caplog.text
    assert "bucket=raw-bucket" in text
    assert "bucket=export-bucket" in text
    assert "check=public-access-block" in text
    assert "Principal" not in text
    assert "AllUsers" not in text
    assert "get_object" not in buckets.calls


def test_attestation_does_not_hide_a_public_policy(monkeypatch):
    buckets = _production_store(
        monkeypatch, attestation="unsupported-store-private", public_policy=True
    )
    with pytest.raises(BucketNotPrivate, match="not private"):
        _storage_client(buckets).ensure_buckets()


def test_unknown_privacy_attestation_is_refused(monkeypatch):
    buckets = _production_store(monkeypatch, attestation="not-a-real-value")
    with pytest.raises(PrivacyAttestationRejected, match="unsupported-store-private"):
        _storage_client(buckets).ensure_buckets()
