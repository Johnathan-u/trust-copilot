"""How long an unreferenced storage object is kept (TC-10-005).

This module is imported while Settings is constructed, so it must not import the ORM or the
database. Object age itself is the store's LastModified; this value is only the grace.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_ORPHAN_GRACE_SECONDS = 7200
MIN_ORPHAN_GRACE_SECONDS = 60
MAX_ORPHAN_GRACE_SECONDS = 7 * 24 * 3600

_grace_clamp_logged = False
_grace_runtime_logged = False


def orphan_grace_seconds() -> int:
    """How long an unreferenced object is kept. Clamped to [60, 604800]. Default 7200.

    An invalid value falls back to 7200, then the same clamp. Callers that pass ``grace_seconds``
    into the sweep use that value instead, so a test can pin the boundary. A setting below
    ``WORKER_JOB_MAX_RUNTIME_SEC`` is logged: an export can upload its object before the row commits.
    """
    global _grace_clamp_logged, _grace_runtime_logged
    raw = (os.environ.get("STORAGE_ORPHAN_GRACE_SECONDS") or "").strip()
    if not raw:
        chosen = DEFAULT_ORPHAN_GRACE_SECONDS
    else:
        try:
            chosen = int(raw)
        except ValueError:
            chosen = DEFAULT_ORPHAN_GRACE_SECONDS
    clamped = min(max(chosen, MIN_ORPHAN_GRACE_SECONDS), MAX_ORPHAN_GRACE_SECONDS)
    if clamped != chosen and not _grace_clamp_logged:
        _grace_clamp_logged = True
        logger.warning(
            "STORAGE_ORPHAN_GRACE_SECONDS must be between %s and %s; using %s",
            MIN_ORPHAN_GRACE_SECONDS,
            MAX_ORPHAN_GRACE_SECONDS,
            clamped,
        )
    try:
        from app.worker_health import job_max_runtime_sec

        runtime = job_max_runtime_sec()
    except Exception:
        runtime = None
    if runtime is not None and clamped < runtime and not _grace_runtime_logged:
        _grace_runtime_logged = True
        logger.warning(
            "STORAGE_ORPHAN_GRACE_SECONDS (%s) is below WORKER_JOB_MAX_RUNTIME_SEC (%s); "
            "an in-flight export object can be deleted before its row commits",
            clamped,
            runtime,
        )
    return clamped
