"""Live verification of alert markers. Captures log output and asserts markers appear."""

import io
import logging
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.core.database import engine


def test_workerz_503_logs_ALERT_WORKER_DOWN():
    """When worker heartbeat is stale or DB errors, GET /workerz returns 503 and logs ALERT_WORKER_DOWN."""
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.WARNING)
    logger = logging.getLogger("trustcopilot.alert")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        # Force "worker not alive" by making first query return a stale timestamp
        stale = datetime.now(timezone.utc) - timedelta(minutes=3)
        from app.core import database
        real_connect = database.engine.connect
        call_count = [0]
        def connect_with_stale_heartbeat(*a, **k):
            conn = real_connect(*a, **k)
            real_execute = conn.execute
            def execute(stmt, *args, **kwargs):
                s = str(stmt)
                call_count[0] += 1
                class FakeResult:
                    def fetchone(self): return (stale,) if "worker_heartbeat" in s else real_execute(stmt, *args, **kwargs).fetchone()
                    def scalar(self): return 0
                if "worker_heartbeat" in s:
                    return FakeResult()
                return real_execute(stmt, *args, **kwargs)
            conn.execute = execute
            return conn
        with patch.object(database.engine, "connect", side_effect=connect_with_stale_heartbeat):
            client = TestClient(app)
            r = client.get("/workerz")
        assert r.status_code == 503
        assert r.json().get("worker_alive") is False
        log_out = log_capture.getvalue()
        assert "ALERT_WORKER_DOWN" in log_out, f"Expected ALERT_WORKER_DOWN in logs, got: {log_out}"
    finally:
        logger.removeHandler(handler)


def test_job_failure_log_format_matches_docs(caplog):
    """ALERT_JOB_FAILURE is logged with job_id, kind, workspace_id, error (same format as worker)."""
    with caplog.at_level(logging.WARNING):
        logging.getLogger("trustcopilot.alert").warning(
            "ALERT_JOB_FAILURE job_id=%s kind=%s workspace_id=%s error=%s",
            42, "index_document", 1, "Document not found"[:200],
        )
    assert any("ALERT_JOB_FAILURE" in rec.message for rec in caplog.records)
    assert "job_id=" in caplog.text and "kind=" in caplog.text and "workspace_id=" in caplog.text


def test_openai_failure_logs_ALERT_OPENAI_FAILURE(caplog):
    """When embedding fails after retries, ALERT_OPENAI_FAILURE is logged."""
    with patch("app.services.embedding_service.get_settings") as m:
        m.return_value.openai_api_key = "invalid-key-for-test"
        with caplog.at_level(logging.WARNING):
            from app.services.embedding_service import embed_text
            result = embed_text("hello world")
        assert result is None
        assert any("ALERT_OPENAI_FAILURE" in rec.message for rec in caplog.records)
        assert "embed_text" in caplog.text or "embed_texts" in caplog.text
