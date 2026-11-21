"""Higher-level file upload/download service (FILE-02, OPS-02)."""

import logging
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

from app.core.config import get_settings  # noqa: E402
from app.core.logging_config import request_id_ctx  # noqa: E402
from app.services.storage import StorageClient  # noqa: E402

PRESIGNED_EXPORT_EXPIRY = 900  # 15 min
ALLOWED_RAW_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt"}
# Sized reads. A body past the cap stops on the next byte instead of one unbounded read.
_UPLOAD_CHUNK_BYTES = 64 * 1024


_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _export_media_type(filename: str) -> str:
    """Content type for an export object. Unknown extensions stay generic."""
    ext = Path(filename).suffix.lower()
    if ext == ".xlsx":
        return _XLSX_MEDIA
    if ext == ".docx":
        return _DOCX_MEDIA
    return "application/octet-stream"


def sanitize_filename(filename: str | None) -> str:
    """Strip path components and unsafe chars; limit length."""
    if not filename or not isinstance(filename, str):
        return "unnamed"
    name = Path(filename).name[:200]
    name = re.sub(r"[^\w\.\-]", "_", name)
    return name or "unnamed"


def validate_storage_key(key: str) -> None:
    """Reject keys that could escape bucket scope.

    The detail does not echo the key. ``nosniff`` is set on the error so a
    browser does not sniff the rejection body.
    """
    headers = {"X-Content-Type-Options": "nosniff"}
    if not key or ".." in key or key.startswith("/") or "\0" in key:
        raise HTTPException(status_code=400, detail="Invalid storage key", headers=headers)
    if len(key) > 600:
        raise HTTPException(status_code=400, detail="Storage key too long", headers=headers)


def make_key(workspace_id: int, prefix: str, filename: str) -> str:
    """Generate storage key: prefix/workspace/uuid_filename."""
    ext = Path(filename).suffix
    return f"{prefix}/{workspace_id}/{uuid.uuid4().hex}{ext}"


_LOG_EXT = re.compile(r"\.[a-z0-9]{1,8}")
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,80}")


def _log_extension(filename: str | None) -> str:
    """Suffix safe to log. A long or odd suffix is not the file's name."""
    if not isinstance(filename, str):
        return "none"
    suffix = Path(filename).suffix.lower()
    if _LOG_EXT.fullmatch(suffix):
        return suffix
    if suffix:
        return "other"
    return "none"


def _http_request_id() -> str:
    """Request id from the logging context, or '-' when it is missing or unsafe to echo."""
    rid = request_id_ctx.get()
    if isinstance(rid, str) and _SAFE_REQUEST_ID.fullmatch(rid):
        return rid
    return "-"


def upload_limit_detail(max_bytes: int) -> str:
    """413 text. A whole number of MiB stays in MB; any other cap is the byte count."""
    mib = max_bytes // (1024 * 1024)
    if mib > 0 and mib * 1024 * 1024 == max_bytes:
        return f"File exceeds max size ({mib}MB)"
    return f"File exceeds max size ({max_bytes} bytes)"


class UploadTooLarge(HTTPException):
    """413 raised when an upload passes the cap. ``observed`` is how far the read got."""

    def __init__(self, max_bytes: int, observed: int, detail: str | None = None) -> None:
        self.max_bytes = max_bytes
        self.observed = observed
        super().__init__(status_code=413, detail=detail or upload_limit_detail(max_bytes))


def read_bounded_upload(
    fileobj: BinaryIO,
    max_bytes: int,
    *,
    detail: str | None = None,
) -> bytes:
    """Read at most ``max_bytes``.

    The byte that crosses the cap, or a chunk that already crosses it, is not
    appended. The function stops there, so the rest of a larger body is not read.
    """
    if max_bytes < 0:
        raise UploadTooLarge(max_bytes, 0, detail) from None
    chunks: list[bytes] = []
    total = 0
    while total < max_bytes:
        want = min(_UPLOAD_CHUNK_BYTES, max_bytes - total)
        chunk = fileobj.read(want)
        if not chunk:
            return b"".join(chunks)
        if len(chunk) > want or total + len(chunk) > max_bytes:
            observed = total + len(chunk)
            chunk = b""
            chunks.clear()
            raise UploadTooLarge(max_bytes, observed, detail) from None
        chunks.append(chunk)
        total += len(chunk)
    extra = fileobj.read(1)
    if extra:
        observed = total + len(extra)
        extra = b""
        chunks.clear()
        raise UploadTooLarge(max_bytes, observed, detail) from None
    return b"".join(chunks)


def _log_upload_rejected(
    *,
    workspace_id: int,
    filename: str | None,
    size_bytes: int,
    reason: str,
    trust_request_id: int | None = None,
    max_bytes: int | None = None,
) -> None:
    """Log a rejected upload without the user-supplied filename.

    ``filename`` is used only to choose ``ext``. The warning carries the workspace,
    the byte size, a short suffix, and the reason. A trust-request rejection also
    carries that request's id. The HTTP request id is included when the request
    context has one. There is no job yet, so this does not invent a ``job_id``.
    """
    ext = _log_extension(filename)
    http_request_id = _http_request_id()
    if trust_request_id is None:
        if reason == "size_exceeded":
            logger.warning(
                "upload_rejected workspace_id=%s size_bytes=%s ext=%s "
                "reason=size_exceeded max_bytes=%s http_request_id=%s",
                workspace_id,
                size_bytes,
                ext,
                max_bytes,
                http_request_id,
            )
            return
        logger.warning(
            "upload_rejected workspace_id=%s size_bytes=%s ext=%s "
            "reason=extension_not_allowed allowed=%s http_request_id=%s",
            workspace_id,
            size_bytes,
            ext,
            sorted(ALLOWED_RAW_EXTENSIONS),
            http_request_id,
        )
        return
    if reason == "size_exceeded":
        logger.warning(
            "upload_rejected trust_request workspace_id=%s request_id=%s "
            "size_bytes=%s ext=%s reason=size_exceeded max_bytes=%s http_request_id=%s",
            workspace_id,
            trust_request_id,
            size_bytes,
            ext,
            max_bytes,
            http_request_id,
        )
        return
    logger.warning(
        "upload_rejected trust_request workspace_id=%s request_id=%s "
        "size_bytes=%s ext=%s reason=extension_not_allowed http_request_id=%s",
        workspace_id,
        trust_request_id,
        size_bytes,
        ext,
        http_request_id,
    )


class FileService:
    """Business-friendly file operations."""

    def __init__(self, storage: StorageClient):
        self._storage = storage

    def upload_raw(
        self,
        workspace_id: int,
        file: UploadFile,
        *,
        before_store: Callable[[bytes], None] | None = None,
    ) -> tuple[str, str]:
        """Upload to raw bucket, return (key, filename). Enforces max size and allowed extensions only.

        ``before_store`` runs after the size check and before the extension check, so a
        questionnaire can refuse a macro workbook (including ``.xlsm``) with the
        workbook check detail. Nothing is stored until both checks pass.
        """
        max_bytes = get_settings().max_upload_bytes
        try:
            content = read_bounded_upload(file.file, max_bytes)
        except UploadTooLarge as exc:
            _log_upload_rejected(
                workspace_id=workspace_id,
                filename=getattr(file, "filename", None),
                size_bytes=exc.observed,
                reason="size_exceeded",
                max_bytes=max_bytes,
            )
            raise
        if before_store is not None:
            before_store(content)
        safe_name = sanitize_filename(file.filename)
        ext = Path(safe_name).suffix.lower()
        if not ext or ext not in ALLOWED_RAW_EXTENSIONS:
            _log_upload_rejected(
                workspace_id=workspace_id,
                filename=file.filename,
                size_bytes=len(content),
                reason="extension_not_allowed",
            )
            raise HTTPException(
                status_code=400,
                detail=f"File must have an allowed extension. Allowed: {', '.join(sorted(ALLOWED_RAW_EXTENSIONS))}",
            )
        key = make_key(workspace_id, "raw", safe_name)
        self._storage.upload(
            self._storage.bucket_raw,
            key,
            content,
            content_type=file.content_type,
        )
        return key, safe_name

    def upload_trust_request_attachment(
        self, workspace_id: int, request_id: int, file: UploadFile
    ) -> tuple[str, str, int]:
        """Upload trust request attachment to raw bucket. Return (key, original_filename, size_bytes)."""
        max_bytes = get_settings().max_upload_bytes
        try:
            content = read_bounded_upload(file.file, max_bytes)
        except UploadTooLarge as exc:
            _log_upload_rejected(
                workspace_id=workspace_id,
                filename=getattr(file, "filename", None),
                size_bytes=exc.observed,
                reason="size_exceeded",
                trust_request_id=request_id,
                max_bytes=max_bytes,
            )
            raise
        safe_name = sanitize_filename(file.filename)
        ext = Path(safe_name).suffix.lower()
        if not ext or ext not in ALLOWED_RAW_EXTENSIONS:
            _log_upload_rejected(
                workspace_id=workspace_id,
                filename=file.filename,
                size_bytes=len(content),
                reason="extension_not_allowed",
                trust_request_id=request_id,
            )
            raise HTTPException(
                status_code=400,
                detail=f"File must have an allowed extension. Allowed: {', '.join(sorted(ALLOWED_RAW_EXTENSIONS))}",
            )
        key = f"trust-requests/{workspace_id}/{request_id}/{uuid.uuid4().hex}{ext}"
        self._storage.upload(
            self._storage.bucket_raw,
            key,
            content,
            content_type=file.content_type,
        )
        return key, safe_name, len(content)

    def download_raw(self, key: str) -> bytes:
        """Download from raw bucket."""
        validate_storage_key(key)
        return self._storage.download(self._storage.bucket_raw, key)

    def delete_raw(self, key: str) -> None:
        """Delete from raw bucket."""
        validate_storage_key(key)
        self._storage.delete(self._storage.bucket_raw, key)

    def upload_export(
        self, workspace_id: int, content: bytes, filename: str, job_id: int | None = None
    ) -> str:
        """Upload export artifact, return key.

        With ``job_id`` (TC-10-003) the key is deterministic per job (``exports/{ws}/job-{id}{ext}``), so a
        re-run of the same export job overwrites its own object instead of leaving an orphan.
        """
        safe_name = sanitize_filename(filename)
        if job_id is not None:
            key = f"exports/{int(workspace_id)}/job-{int(job_id)}{Path(safe_name).suffix}"
            validate_storage_key(key)
        else:
            key = make_key(workspace_id, "exports", safe_name)
        self._storage.upload(
            self._storage.bucket_exports,
            key,
            content,
            content_type=_export_media_type(safe_name),
        )
        return key

    def get_download_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """Get presigned download URL. Validates key to prevent path traversal."""
        validate_storage_key(key)
        return self._storage.get_presigned_url(bucket, key, expires_in)
