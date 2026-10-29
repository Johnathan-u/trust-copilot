"""Best-effort object cleanup when an upload transaction rolls back (TC-10-003c)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The row does not exist when the client key is claimed, so the scope's resource slot is this
# constant. One key is one in-flight upload per workspace and route; a retry replays that upload.
UPLOAD_IDEMPOTENCY_RESOURCE = "new"


def discard_stored_upload(storage, key: str | None) -> None:
    """Delete an object whose database row is being rolled back. Failures are logged, not raised."""
    if not key:
        return
    try:
        storage.delete(storage.bucket_raw, key)
    except Exception:
        logger.warning(
            "upload: failed to delete stored object after rolled-back upload key=%s",
            key,
            exc_info=True,
        )
