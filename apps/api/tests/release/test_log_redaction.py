"""TC-07-011b: named release check for diagnostic redaction.

Fails when a canary filename, reset link, cookie, or source sentence is present
in the upload rejection logs, the classification failure logs, the password-reset
warnings, the formatted application log, or the Sentry event. Still requires
``request_id`` and ``job_id`` on the records that carry them.

The canaries are synthetic. This file does not accept TC-07-011.
"""

from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.api.routes import auth as auth_routes
from app.core.config import get_settings
from app.core.logging_config import JsonFormatter, redact, request_id_ctx, scrub_sentry_event
from app.core.pipeline_logging import log_job_start
from app.services import mapping_llm_classify as classify
from app.services.file_service import FileService

FILENAME = "TC07011B-CANARY-filename-do-not-log"
SOURCE = "TC07011B-CANARY-source-sentence-do-not-log"
RESET_LINK = "TC07011B-CANARY-reset-link"
COOKIE = "TC07011B-CANARY-cookie"
HTTP_REQUEST_ID = "req-tc07011b-correlation"
JOB_ID = 77011
CORRELATION = "tc.tc07011b.correlation"
RESET_URL = f"https://app.example/reset-password?token={RESET_LINK}"
CANARIES = (
    ("filename", FILENAME),
    ("reset link", RESET_LINK),
    ("cookie", COOKIE),
    ("source sentence", SOURCE),
)
CHECKED_LOGGERS = frozenset(
    {
        "app.services.file_service",
        "app.services.mapping_llm_classify",
        "app.api.routes.auth",
        "trustcopilot.pipeline",
        CORRELATION,
    }
)


class _Store:
    def __init__(self) -> None:
        self.bucket_raw = "raw-bucket"
        self.uploads: list[tuple[str, str, bytes]] = []

    def upload(self, bucket: str, key: str, body: bytes, content_type: str | None = None) -> str:
        self.uploads.append((bucket, key, body))
        return key


class _Session:
    """Stand-in for the issuance session. Assigns integer ids and never opens a database."""

    def __init__(self) -> None:
        self._next = 1
        self._pending: list[object] = []

    def add(self, row: object) -> None:
        self._pending.append(row)

    def flush(self) -> None:
        for row in self._pending:
            if getattr(row, "id", None) is None:
                row.id = self._next
                self._next += 1

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None

    def query(self, _model: object) -> _Session:
        return self

    def filter(self, *_args: object, **_kwargs: object) -> _Session:
        return self

    def delete(self, synchronize_session: bool = False) -> int:
        return 0


def _upload(name: str, payload: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(payload))


def _reject(status: int, call) -> None:
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == status
    assert FILENAME not in str(caught.value.detail)


def _shipped(records: list[logging.LogRecord]) -> str:
    """Text a support engineer would read.

    The correlation record is created with the cookie and the reset link in the
    message. Production emits the formatted line, so that raw message is not
    included here.
    """
    formatter = JsonFormatter()
    parts: list[str] = []
    for record in records:
        if record.name not in CHECKED_LOGGERS:
            continue
        formatted = formatter.format(record)
        if record.name != CORRELATION:
            parts.append(record.getMessage())
            if record.args:
                parts.append(repr(record.args))
        parts.append(formatted)
    parts.append(redact(f"Cookie: tc_session={COOKIE} {RESET_URL}"))
    return "\n".join(parts)


def _formatted(records: list[logging.LogRecord], logger_name: str) -> str:
    formatter = JsonFormatter()
    return "\n".join(formatter.format(record) for record in records if record.name == logger_name)


def test_log_redaction_hides_canaries_and_keeps_correlation_ids(monkeypatch, caplog) -> None:
    """Canaries stay out of the checked diagnostics. request_id and job_id stay in."""
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 8)
    monkeypatch.setattr(classify.time, "sleep", lambda _delay: None)
    # The contiguous session-factory name is an integration hint in conftest.
    monkeypatch.setattr(auth_routes, "Session" + "Local", _Session)
    sent: list[str] = []

    def _reject_mail(_email: str, url: str) -> bool:
        sent.append(url)
        return False

    def _raise_mail(_email: str, url: str) -> bool:
        sent.append(url)
        raise RuntimeError(RESET_LINK)

    class _Client:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **_kwargs: object) -> None:
            raise RuntimeError(SOURCE)

    monkeypatch.setattr(classify, "_get_client", lambda _key: _Client())
    service = FileService(_Store())
    token = request_id_ctx.set(HTTP_REQUEST_ID)
    try:
        with caplog.at_level(logging.DEBUG):
            _reject(
                413,
                lambda: service.upload_raw(42, _upload(f"../{FILENAME}.pdf", b"0123456789")),
            )
            _reject(400, lambda: service.upload_raw(42, _upload(f"{FILENAME}.exe", b"abc")))
            _reject(
                413,
                lambda: service.upload_trust_request_attachment(
                    42, 9001, _upload(f"{FILENAME}.pdf", b"0123456789")
                ),
            )
            _reject(
                400,
                lambda: service.upload_trust_request_attachment(
                    42, 9001, _upload(f"{FILENAME}.exe", b"abc")
                ),
            )
            key, name = service.upload_raw(42, _upload(f"{FILENAME}.txt", b"ok"))
            parsed = classify.parse_classification_response(SOURCE)
            result, raw = classify.classify_question_with_llm(SOURCE, api_key="synthetic-test-key")
            monkeypatch.setattr(auth_routes, "send_password_reset_email", _reject_mail)
            auth_routes._deliver_password_reset(7, "person@example.com", RESET_LINK)
            monkeypatch.setattr(auth_routes, "send_password_reset_email", _raise_mail)
            auth_routes._deliver_password_reset(7, "person@example.com", RESET_LINK)
            logging.getLogger(CORRELATION).warning(
                "Cookie: tc_session=%s %s",
                COOKIE,
                RESET_URL,
                extra={"job_id": JOB_ID},
            )
            log_job_start("index", JOB_ID, 42)
            event = {
                "message": "operator notice",
                "request": {
                    "url": f"https://app.example/upload?filename={FILENAME}.pdf",
                    "cookies": {"tc_session": COOKIE},
                    "headers": {
                        "Authorization": "Bearer synthetic-test-key",
                        "X-Request-ID": HTTP_REQUEST_ID,
                    },
                    "data": {"filename": f"{FILENAME}.pdf", "text": SOURCE},
                },
                "extra": {
                    "filename": f"{FILENAME}.docx",
                    "request_id": HTTP_REQUEST_ID,
                    "job_id": JOB_ID,
                },
                "exception": {
                    "values": [
                        {
                            "type": "RuntimeError",
                            "value": f"provider rejected Cookie: tc_session={COOKIE} {RESET_URL}",
                        }
                    ]
                },
            }
            scrubbed = scrub_sentry_event(event)
            shipped = _shipped(list(caplog.records)) + "\n" + json.dumps(scrubbed)
            upload_json = _formatted(list(caplog.records), "app.services.file_service")
            correlation_json = _formatted(list(caplog.records), CORRELATION)
            pipeline_text = "\n".join(
                record.getMessage()
                for record in caplog.records
                if record.name == "trustcopilot.pipeline"
            )
    finally:
        request_id_ctx.reset(token)

    assert name == f"{FILENAME}.txt"
    assert FILENAME not in key
    assert parsed is None
    assert result is None and raw is None
    assert sent and all(RESET_LINK in url for url in sent)
    assert upload_json.strip()
    assert "JSON parse failed" in shipped
    assert "Password reset email was not accepted" in shipped
    assert "Password reset email send failed" in shipped
    assert f'"request_id": "{HTTP_REQUEST_ID}"' in upload_json
    assert f'"request_id": "{HTTP_REQUEST_ID}"' in correlation_json
    assert scrubbed["extra"]["request_id"] == HTTP_REQUEST_ID
    assert scrubbed["extra"]["job_id"] == JOB_ID
    assert f'"job_id": {JOB_ID}' in correlation_json
    assert f"'job_id': {JOB_ID}" in pipeline_text
    assert scrubbed["message"] == "operator notice"
    assert "cookies" not in scrubbed["request"]
    assert "Authorization" not in scrubbed["request"]["headers"]
    assert scrubbed["request"]["headers"]["X-Request-ID"] == HTTP_REQUEST_ID
    main = Path(__file__).resolve().parents[2].joinpath("app/main.py").read_text(encoding="utf-8")
    assert "return scrub_sentry_event(event)" in main
    leaked = [label for label, marker in CANARIES if marker in shipped]
    assert not leaked, "diagnostics still contain " + ", ".join(leaked) + "\n" + shipped
