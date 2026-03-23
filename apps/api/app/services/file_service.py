"""Higher-level file upload/download service (FILE-02, OPS-02)."""

import logging
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

from app.core.config import get_settings
from app.services.storage import StorageClient

PRESIGNED_EXPORT_EXPIRY = 900  # 15 min
ALLOWED_RAW_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt"}


def sanitize_filename(filename: str | None) -> str:
    """Strip path components and unsafe chars; limit length."""
    if not filename or not isinstance(filename, str):
        return "unnamed"
    name = Path(filename).name[:200]
    name = re.sub(r"[^\w\.\-]", "_", name)
    return name or "unnamed"


def validate_storage_key(key: str) -> None:
    """Reject keys that could escape bucket scope."""
    if not key or ".." in key or key.startswith("/") or "\0" in key:
        raise HTTPException(status_code=400, detail="Invalid storage key")
    if len(key) > 600:
        raise HTTPException(status_code=400, detail="Storage key too long")


def make_key(workspace_id: int, prefix: str, filename: str) -> str:
    """Generate storage key: prefix/workspace/uuid_filename."""
    ext = Path(filename).suffix
    return f"{prefix}/{workspace_id}/{uuid.uuid4().hex}{ext}"


class FileService:
    """Business-friendly file operations."""

    def __init__(self, storage: StorageClient):
        self._storage = storage

    def upload_raw(self, workspace_id: int, file: UploadFile) -> tuple[str, str]:
        """Upload to raw bucket, return (key, filename). Enforces max size and allowed extensions only."""
        content = file.file.read()
        max_bytes = get_settings().max_upload_bytes
        if len(content) > max_bytes:
            logger.warning("upload_rejected workspace_id=%s filename=%s reason=size_exceeded max_bytes=%s", workspace_id, getattr(file, "filename", ""), max_bytes)
            raise HTTPException(status_code=413, detail=f"File exceeds max size ({max_bytes // (1024*1024)}MB)")
        safe_name = sanitize_filename(file.filename)
        ext = Path(safe_name).suffix.lower()
        if not ext or ext not in ALLOWED_RAW_EXTENSIONS:
            logger.warning("upload_rejected workspace_id=%s filename=%s ext=%s reason=extension_not_allowed allowed=%s", workspace_id, safe_name, ext, sorted(ALLOWED_RAW_EXTENSIONS))
            raise HTTPException(status_code=400, detail=f"File must have an allowed extension. Allowed: {', '.join(sorted(ALLOWED_RAW_EXTENSIONS))}")
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
        content = file.file.read()
        max_bytes = get_settings().max_upload_bytes
        if len(content) > max_bytes:
            logger.warning("upload_rejected trust_request workspace_id=%s request_id=%s filename=%s reason=size_exceeded", workspace_id, request_id, getattr(file, "filename", ""))
            raise HTTPException(status_code=413, detail=f"File exceeds max size ({max_bytes // (1024*1024)}MB)")
        safe_name = sanitize_filename(file.filename)
        ext = Path(safe_name).suffix.lower()
        if not ext or ext not in ALLOWED_RAW_EXTENSIONS:
            logger.warning("upload_rejected trust_request workspace_id=%s filename=%s ext=%s reason=extension_not_allowed", workspace_id, safe_name, ext)
            raise HTTPException(status_code=400, detail=f"File must have an allowed extension. Allowed: {', '.join(sorted(ALLOWED_RAW_EXTENSIONS))}")
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

    def upload_export(self, workspace_id: int, content: bytes, filename: str) -> str:
        """Upload export artifact, return key."""
        safe_name = sanitize_filename(filename)
        key = make_key(workspace_id, "exports", safe_name)
        self._storage.upload(
            self._storage.bucket_exports,
            key,
            content,
            content_type="application/octet-stream",
        )
        return key

    def get_download_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """Get presigned download URL. Validates key to prevent path traversal."""
        validate_storage_key(key)
        return self._storage.get_presigned_url(bucket, key, expires_in)
