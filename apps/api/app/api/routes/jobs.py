"""Job status API (JOB-03).

Exposes lifecycle fields for UI polling. Status values match ``JobStatus`` in ``app.models.job``:
``queued`` → ``running`` → ``completed`` | ``failed`` (``cancelled`` reserved).
For ``generate_answers`` jobs, ``result`` may contain JSON ``{"generated": N, "total": M}`` while running.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_review
from app.core.database import get_db
from app.models import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])
_log = logging.getLogger(__name__)


@router.get("/{job_id}")
def get_job(
    job_id: int,
    workspace_id: int = Query(..., description="Required for workspace isolation"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Get job status for UI polling. Requires auth and workspace access."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    job = db.query(Job).filter(Job.id == job_id, Job.workspace_id == workspace_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _log.info(
        "API: job status fetched job_id=%s kind=%s status=%s workspace_id=%s",
        job.id,
        job.kind,
        job.status,
        workspace_id,
    )
    result_payload = None
    if job.result:
        try:
            result_payload = json.loads(job.result)
        except json.JSONDecodeError:
            result_payload = job.result
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "attempt": job.attempt,
        "error": job.error,
        "result": result_payload,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
