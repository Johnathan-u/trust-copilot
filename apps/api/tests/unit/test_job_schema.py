"""Job response schema. Timestamps format; a missing timestamp stays null."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.job import job_response

pytestmark = pytest.mark.unit


def test_job_response_formats_present_timestamps_and_keeps_nulls():
    started = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    job = SimpleNamespace(
        id=7,
        workspace_id=3,
        kind="answer",
        status="failed",
        payload="{}",
        result=None,
        error="stored separately from the safe envelope",
        attempt=2,
        max_attempts=3,
        started_at=started,
        completed_at=None,
        created_at=started,
    )
    body = job_response(job)
    assert body["id"] == 7
    assert body["workspace_id"] == 3
    assert body["status"] == "failed"
    assert body["started_at"] == started.isoformat()
    assert body["created_at"] == started.isoformat()
    assert body["completed_at"] is None
    assert body["attempt"] == 2
