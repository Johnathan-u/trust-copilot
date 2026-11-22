"""SHA-256 agreement for original documents and export objects (TC-10-006).

A download is refused until the row records a hash that matches the object
bytes, and the row's version, media type, and workspace match that object.
Rows written before the columns existed stay null. They are not streamed.
``python -m app.services.storage_checksum`` hashes the current object and
fills the row. Until that command runs with ``--execute``, the download
stays refused.

The command prints counts only. It does not print a storage key or a hash.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

logger = logging.getLogger(__name__)

CHECKSUM_DETAIL = "The stored file could not be verified."
NOSNIFF_HEADER = {"X-Content-Type-Options": "nosniff"}
OBJECT_VERSION_START = 1

_DOCUMENT_MEDIA = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_sha256(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    if any(char not in "0123456789abcdef" for char in value):
        return None
    return value


def positive_version(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1:
        return None
    return value


def document_media_type(filename: str | None) -> str:
    suffix = Path(Path(filename or "").name).suffix.lower()
    return _DOCUMENT_MEDIA.get(suffix, "application/octet-stream")


def key_workspace(key: object) -> int | None:
    """Workspace id encoded as the second segment of ``raw/{id}/`` or ``exports/{id}/``."""
    if not isinstance(key, str) or not key:
        return None
    parts = key.split("/")
    if len(parts) < 3 or parts[0] not in ("raw", "exports"):
        return None
    if not parts[1].isdigit() or parts[1].startswith("0"):
        return None
    return int(parts[1])


def checksum_metadata(
    workspace_id: int, digest: str, version: int, media_type: str
) -> dict[str, str]:
    return {
        "sha256": digest,
        "version": str(version),
        "workspace-id": str(workspace_id),
        "media-type": media_type,
    }


def checksum_http_error() -> HTTPException:
    """Fixed 409. The detail does not include a key or a hash."""
    return HTTPException(status_code=409, detail=CHECKSUM_DETAIL, headers=dict(NOSNIFF_HEADER))


class ChecksumRefusal(Exception):
    """The bytes must not be returned. The message is not shown to the client."""


def _accepts_keyword(func, name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if param.name == name:
            return True
    return False


def store_bytes(
    storage,
    bucket: str,
    key: str,
    content: bytes,
    content_type: str,
    metadata: dict[str, str],
) -> str:
    """Put ``content`` and, when the store accepts it, the checksum metadata."""
    upload = storage.upload
    kwargs: dict = {"content_type": content_type}
    if _accepts_keyword(upload, "metadata"):
        kwargs["metadata"] = metadata
    return upload(bucket, key, content, **kwargs)


def read_object(storage, bucket: str, key: str) -> tuple[bytes, dict[str, str] | None]:
    """Return bytes and metadata.

    ``None`` metadata means this store cannot report it (an in-memory fake).
    A real store returns a dict, and an empty dict does not agree.
    """
    checked = getattr(storage, "download_checksummed", None)
    if checked is not None:
        body, meta = checked(bucket, key)
        cleaned = {
            str(name).lower(): str(value)
            for name, value in dict(meta or {}).items()
            if isinstance(name, str) and isinstance(value, str)
        }
        return bytes(body), cleaned
    download = getattr(storage, "download", None)
    if download is not None:
        return bytes(download(bucket, key)), None
    chunks: list[bytes] = []
    for chunk in storage.download_stream(bucket, key):
        if isinstance(chunk, str):
            chunk = chunk.encode()
        chunks.append(bytes(chunk))
    return b"".join(chunks), None


def metadata_agrees(
    meta: dict[str, str],
    *,
    digest: str,
    version: int,
    media_type: str,
    workspace_id: int,
) -> bool:
    if meta.get("sha256") != digest:
        return False
    if meta.get("version") != str(version):
        return False
    if meta.get("workspace-id") != str(workspace_id):
        return False
    if meta.get("media-type") != media_type:
        return False
    content_type = meta.get("content-type")
    if content_type and content_type != media_type:
        return False
    return True


def load_agreed_bytes(
    storage,
    bucket: str,
    key: str,
    *,
    digest: str,
    version: int,
    media_type: str,
    workspace_id: int,
) -> bytes:
    """Read the object only after the key's workspace matches, then check the bytes.

    A missing object, a hash mismatch, or metadata that disagrees raises
    ``ChecksumRefusal``. The exception does not carry the key or the hash.
    """
    if key_workspace(key) != workspace_id:
        raise ChecksumRefusal()
    if (
        valid_sha256(digest) is None
        or positive_version(version) is None
        or not isinstance(media_type, str)
        or not media_type
    ):
        raise ChecksumRefusal()
    try:
        payload, meta = read_object(storage, bucket, key)
    except ChecksumRefusal:
        raise
    except Exception:
        raise ChecksumRefusal() from None
    if sha256_hex(payload) != digest:
        raise ChecksumRefusal()
    if meta is not None and not metadata_agrees(
        meta,
        digest=digest,
        version=version,
        media_type=media_type,
        workspace_id=workspace_id,
    ):
        raise ChecksumRefusal()
    return payload


@dataclass
class BackfillReport:
    pending: int = 0
    updated: int = 0
    missing: int = 0
    disagreed: int = 0
    mismatched: int = 0


def format_report(report: BackfillReport, *, execute: bool) -> str:
    mode = "execute" if execute else "dry-run"
    return (
        f"{mode} pending={report.pending} updated={report.updated} "
        f"missing={report.missing} disagreed={report.disagreed} "
        f"mismatched={report.mismatched}"
    )


def _export_media(filename: str | None) -> str | None:
    from app.services.export_service import media_type_for_filename

    return media_type_for_filename(filename or "")


def _read_for_backfill(storage, bucket: str, key: str) -> bytes | None:
    try:
        payload, _meta = read_object(storage, bucket, key)
    except Exception:
        return None
    return payload


def _stamp(storage, bucket: str, key: str, payload: bytes, media: str, metadata: dict) -> None:
    store_bytes(storage, bucket, key, payload, media, metadata)


def _backfill_document(row, storage, *, execute: bool, report: BackfillReport) -> None:
    from app.services.file_service import validate_storage_key

    key = row.storage_key or ""
    if key_workspace(key) != row.workspace_id:
        report.disagreed += 1
        return
    try:
        validate_storage_key(key)
    except Exception:
        report.disagreed += 1
        return
    payload = _read_for_backfill(storage, storage.bucket_raw, key)
    if payload is None:
        report.missing += 1
        return
    digest = sha256_hex(payload)
    media = document_media_type(row.filename)
    version = OBJECT_VERSION_START
    recorded = valid_sha256(row.content_sha256)
    if recorded is not None and recorded != digest:
        report.mismatched += 1
        return
    complete = (
        recorded == digest
        and positive_version(row.object_version) == version
        and row.object_media_type == media
    )
    if complete:
        return
    if not execute:
        report.pending += 1
        return
    _stamp(
        storage,
        storage.bucket_raw,
        key,
        payload,
        media,
        checksum_metadata(row.workspace_id, digest, version, media),
    )
    row.content_sha256 = digest
    row.object_version = version
    row.object_media_type = media
    report.updated += 1


def _job_for_export(session, row):
    from app.models import Job

    job_id = getattr(row, "job_id", None)
    if not isinstance(job_id, int) or isinstance(job_id, bool):
        return None
    return session.query(Job).filter(Job.id == job_id, Job.workspace_id == row.workspace_id).first()


def _backfill_export(session, row, storage, *, execute: bool, report: BackfillReport) -> None:
    from app.services.export_service import recorded_export_file
    from app.services.file_service import validate_storage_key

    if (row.status or "completed") != "completed":
        return
    key = row.storage_key or ""
    if key_workspace(key) != row.workspace_id:
        report.disagreed += 1
        return
    try:
        validate_storage_key(key)
    except Exception:
        report.disagreed += 1
        return
    media = _export_media(row.filename)
    if media is None:
        report.disagreed += 1
        return
    payload = _read_for_backfill(storage, storage.bucket_exports, key)
    if payload is None:
        report.missing += 1
        return
    digest = sha256_hex(payload)
    job = _job_for_export(session, row)
    recorded_job = recorded_export_file(job.result if job is not None else None)
    if recorded_job is not None and (
        recorded_job["sha256"] != digest or recorded_job["content_type"] != media
    ):
        report.mismatched += 1
        return
    recorded = valid_sha256(row.content_sha256)
    if recorded is not None and recorded != digest:
        report.mismatched += 1
        return
    version = OBJECT_VERSION_START
    complete = (
        recorded == digest
        and positive_version(row.object_version) == version
        and row.content_type == media
    )
    if complete:
        return
    if not execute:
        report.pending += 1
        return
    _stamp(
        storage,
        storage.bucket_exports,
        key,
        payload,
        media,
        checksum_metadata(row.workspace_id, digest, version, media),
    )
    row.content_sha256 = digest
    row.object_version = version
    row.content_type = media
    report.updated += 1


def backfill_storage_checksums(session, storage, *, execute: bool) -> BackfillReport:
    """Fill null document and completed-export hashes from the current object.

    Dry-run (``execute`` false) changes nothing. A key whose workspace segment
    disagrees with the row is left null. An export whose job hash disagrees
    with the bytes is left null. A missing object is left null.
    """
    from app.models import Document, ExportRecord

    report = BackfillReport()
    documents = session.query(Document).order_by(Document.id).all()
    exports = session.query(ExportRecord).order_by(ExportRecord.id).all()
    for row in documents:
        _backfill_document(row, storage, execute=execute, report=report)
        if execute:
            session.commit()
    for row in exports:
        _backfill_export(session, row, storage, execute=execute, report=report)
        if execute:
            session.commit()
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record SHA-256 hashes for documents and completed exports that have none. "
            "Dry-run is the default. Pass --execute to write. Prints counts only."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write hashes. Without this flag the command only counts what it would write.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint. Dry-run unless ``--execute`` is present. Not an HTTP route."""
    from app.core.database import SessionLocal
    from app.services.storage import StorageClient

    args = parse_args(argv)
    session = SessionLocal()
    try:
        storage = StorageClient()
        report = backfill_storage_checksums(session, storage, execute=args.execute)
    except Exception:
        logger.warning("storage checksum backfill failed")
        print("storage checksum backfill failed")
        return 2
    finally:
        session.close()
    print(format_report(report, execute=args.execute))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
