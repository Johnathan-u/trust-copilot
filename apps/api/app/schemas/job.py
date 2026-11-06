"""Job schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class JobView(Protocol):
    """Fields ``job_response`` reads. Structural so callers can pass a row or a stand-in."""

    id: object
    workspace_id: object
    kind: object
    status: object
    payload: object
    result: object
    error: object
    attempt: object
    max_attempts: object
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime | None


def job_response(job: JobView) -> dict[str, object]:
    """Serialize job for API."""
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "kind": job.kind,
        "status": job.status,
        "payload": job.payload,
        "result": job.result,
        "error": job.error,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
