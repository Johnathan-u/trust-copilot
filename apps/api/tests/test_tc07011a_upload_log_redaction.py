"""TC-07-011a: upload logs, classification logs, and Sentry events omit sensitive text."""

import json
import logging
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.core.config import get_settings
from app.core.logging_config import JsonFormatter, request_id_ctx, scrub_sentry_event
from app.services.file_service import FileService

CANARY = "TC07011A-CANARY-filename-do-not-log"
SOURCE = "TC07011A-CANARY-source-sentence-do-not-log"
LINK_MARKER = "TC07011A-CANARY-reset-link"
HTTP_REQUEST_ID = "req-tc07011a-correlation"
LOGGER = "app.services.file_service"


class _Store:
    def __init__(self) -> None:
        self.bucket_raw = "raw-bucket"
        self.uploads: list[tuple[str, str, bytes]] = []

    def upload(self, bucket: str, key: str, body: bytes, content_type: str | None = None) -> str:
        self.uploads.append((bucket, key, body))
        return key


def _upload(name: str, payload: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(payload))


def _rendered(caplog: pytest.LogCaptureFixture, logger_name: str = LOGGER) -> str:
    formatter = JsonFormatter()
    parts: list[str] = []
    for record in caplog.records:
        if record.name != logger_name:
            continue
        parts.append(record.getMessage())
        if record.args:
            parts.append(repr(record.args))
        parts.append(formatter.format(record))
    return "\n".join(parts)


def _reject(status: int, call) -> None:
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == status
    assert CANARY not in str(caught.value.detail)


def test_upload_logs_omit_the_user_filename(monkeypatch, caplog) -> None:
    """A distinctive filename is rejected and stored without being written to the log."""
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 8)
    service = FileService(_Store())
    token = request_id_ctx.set(HTTP_REQUEST_ID)
    try:
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            _reject(
                413,
                lambda: service.upload_raw(42, _upload(f"../{CANARY}.pdf", b"0123456789")),
            )
            _reject(400, lambda: service.upload_raw(42, _upload(f"{CANARY}.exe", b"abc")))
            _reject(400, lambda: service.upload_raw(42, _upload(CANARY, b"abc")))
            _reject(400, lambda: service.upload_raw(42, _upload(f"notes.{CANARY}", b"abc")))
            _reject(
                413,
                lambda: service.upload_trust_request_attachment(
                    42, 9001, _upload(f"{CANARY}.pdf", b"0123456789")
                ),
            )
            _reject(
                400,
                lambda: service.upload_trust_request_attachment(
                    42, 9001, _upload(f"{CANARY}.exe", b"abc")
                ),
            )
            key, name = service.upload_raw(42, _upload(f"{CANARY}.txt", b"ok"))
        rendered = _rendered(caplog)
    finally:
        request_id_ctx.reset(token)

    assert name == f"{CANARY}.txt"
    assert CANARY not in key
    assert rendered.strip()
    assert CANARY not in rendered
    assert "filename=" not in rendered
    assert "workspace_id=42" in rendered
    # The reader stops on the first byte past the 8-byte cap, so the log records 9.
    assert "size_bytes=9" in rendered
    assert "size_bytes=3" in rendered
    assert "ext=.pdf" in rendered
    assert "ext=.exe" in rendered
    assert "ext=none" in rendered
    assert "ext=other" in rendered
    assert "reason=size_exceeded" in rendered
    assert "reason=extension_not_allowed" in rendered
    assert "max_bytes=8" in rendered
    assert "request_id=9001" in rendered
    assert f"http_request_id={HTTP_REQUEST_ID}" in rendered
    assert f'"request_id": "{HTTP_REQUEST_ID}"' in rendered
    assert "job_id" not in rendered


def test_classification_logs_omit_source_text(monkeypatch, caplog) -> None:
    """A failed classification records the failure, not the question or model text."""
    from app.services import mapping_llm_classify as classify

    monkeypatch.setattr(classify.time, "sleep", lambda _delay: None)

    class _Client:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **_kwargs: object) -> None:
            raise RuntimeError(SOURCE)

    monkeypatch.setattr(classify, "_get_client", lambda _key: _Client())
    with caplog.at_level(logging.WARNING, logger=classify.logger.name):
        parsed = classify.parse_classification_response(SOURCE)
        result, raw = classify.classify_question_with_llm(SOURCE, api_key="synthetic-test-key")
    rendered = _rendered(caplog, classify.logger.name)
    assert parsed is None
    assert result is None and raw is None
    assert rendered.strip()
    assert SOURCE not in rendered
    assert "JSON parse failed" in rendered
    assert "bytes=" in rendered
    assert "RuntimeError" in rendered


def test_sentry_event_drops_filename_reset_link_and_source_body() -> None:
    """Sentry keeps request and job ids and drops the body, filename, and reset token."""
    event = {
        "message": "operator notice",
        "request": {
            "url": f"https://app.example/upload?filename={CANARY}.pdf",
            "cookies": {"tc_session": "secret-cookie"},
            "headers": {
                "Authorization": "Bearer secret-token",
                "X-Request-ID": HTTP_REQUEST_ID,
            },
            "data": {"filename": f"{CANARY}.pdf", "text": SOURCE},
        },
        "extra": {
            "filename": f"{CANARY}.docx",
            "request_id": HTTP_REQUEST_ID,
            "job_id": 77,
        },
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": (
                        "provider rejected "
                        f"https://app.example/reset-password?token={LINK_MARKER}"
                    ),
                }
            ]
        },
    }
    scrubbed = scrub_sentry_event(event)
    blob = json.dumps(scrubbed)
    assert CANARY not in blob
    assert SOURCE not in blob
    assert LINK_MARKER not in blob
    assert "secret-cookie" not in blob
    assert "secret-token" not in blob
    assert "cookies" not in scrubbed["request"]
    assert "data" not in scrubbed["request"]
    assert "Authorization" not in scrubbed["request"]["headers"]
    assert scrubbed["request"]["headers"]["X-Request-ID"] == HTTP_REQUEST_ID
    assert scrubbed["extra"]["request_id"] == HTTP_REQUEST_ID
    assert scrubbed["extra"]["job_id"] == 77
    assert scrubbed["extra"]["filename"] == "[REDACTED]"
    assert scrubbed["message"] == "operator notice"
    assert "reset-password?token=[REDACTED]" in blob
    source = Path(__file__).resolve().parents[1].joinpath("app/main.py").read_text(encoding="utf-8")
    assert "return scrub_sentry_event(event)" in source
