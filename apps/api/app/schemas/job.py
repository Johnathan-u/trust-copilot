"""Job schemas."""

from datetime import datetime


def job_response(job) -> dict:
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
