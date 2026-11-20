"""Structured logging: JSON to stdout in production, level from LOG_LEVEL."""

import json
import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

# Request-scoped context (set by middleware)
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
workspace_id_ctx: ContextVar[int | None] = ContextVar("workspace_id", default=None)


# Standard LogRecord attributes to skip when merging extra
_RESERVED = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "message",
        "taskName",
    }
)


# TC-07-001: keep signing material, cookies and credentials out of logs and traces.
_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|"
    r"session|credential|signature|dsn|database_url)",
    re.IGNORECASE,
)
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # tc_session=<base64 payload>.<hmac>
    (re.compile(r"(tc_session=)[^;\s\"']+"), r"\1[REDACTED]"),
    # bare signed session tokens (base64 JSON payload + 64-hex HMAC)
    (re.compile(r"eyJ[A-Za-z0-9_\-]+=*\.[0-9a-f]{64}\b"), "[REDACTED_SESSION_TOKEN]"),
    # Authorization: Bearer/Basic <value>
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/\-]+=*"), r"\1 [REDACTED]"),
    # scheme://user:password@host
    (re.compile(r"([a-z][a-z0-9+.\-]*://[^:/@\s\"']+:)[^@/\s\"']+@"), r"\1[REDACTED]@"),
    # presigned S3 URL signing parameters
    (
        re.compile(r"(?i)(X-Amz-(?:Signature|Credential|Security-Token)=)[^&\s\"']+"),
        r"\1[REDACTED]",
    ),
    # key=value / "key": "value" for secret-named keys
    (
        re.compile(
            r"(?i)((?:password|passwd|secret|token|api_key|apikey|access_key|secret_key)[\"']?\s*[:=]\s*[\"']?)"
            r"[^\s\"',;&]{4,}"
        ),
        r"\1[REDACTED]",
    ),
)


def redact(text: str) -> str:
    """Mask cookies, bearer tokens, URL credentials and secret-named values in free text."""
    if not text:
        return text
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


# TC-07-011a: monitoring events must not carry filenames, reset links, or source bodies.
_FILENAME_KEY = re.compile(r"(?i)(?:^|[._-])file[_-]?name$")
_FILENAME_PAIR = re.compile(r"(?i)((?:^|[?&\s\"'])file[_-]?name=)[^&\s\"']+")
_FILENAME_JSON = re.compile(r'(?i)("file[_-]?name"\s*:\s*")[^"]*')
_RESET_LINK = re.compile(
    r"(?i)((?:https?://[^\s\"']*)?/reset-password\?[^\"'\s]*?\btoken=)[^\"'\s&]+"
)
_REQUEST_BODY_KEYS = frozenset({"data", "cookies", "body"})


def _scrub_monitoring_text(text: str) -> str:
    """Mask secrets, reset-link tokens, and filename pairs in one monitoring string."""
    text = redact(text)
    text = _RESET_LINK.sub(r"\1[REDACTED]", text)
    text = _FILENAME_PAIR.sub(r"\1[REDACTED]", text)
    text = _FILENAME_JSON.sub(r"\1[REDACTED]", text)
    return text


def _drop_authorization(headers: Any) -> Any:
    if isinstance(headers, dict):
        return {key: value for key, value in headers.items() if str(key).lower() != "authorization"}
    if isinstance(headers, list):
        kept = []
        for item in headers:
            if isinstance(item, (list, tuple)) and item and str(item[0]).lower() == "authorization":
                continue
            kept.append(item)
        return kept
    return headers


def _scrub_monitoring_inplace(obj: Any) -> None:
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if (
                isinstance(key, str)
                and _SENSITIVE_KEY.search(key)
                and value not in (None, "", 0, False)
            ):
                obj[key] = "[REDACTED]"
            elif isinstance(key, str) and isinstance(value, str) and _FILENAME_KEY.search(key):
                obj[key] = "[REDACTED]"
            elif isinstance(value, str):
                obj[key] = _scrub_monitoring_text(value)
            elif isinstance(value, (dict, list)):
                _scrub_monitoring_inplace(value)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            if isinstance(value, str):
                obj[index] = _scrub_monitoring_text(value)
            elif isinstance(value, (dict, list)):
                _scrub_monitoring_inplace(value)


def scrub_sentry_event(event: dict) -> dict:
    """Remove filenames, reset links, and request bodies from a Sentry event.

    Cookies and the Authorization header are dropped. ``request_id`` and ``job_id``
    are left as they are. The event is updated in place and returned.
    """
    request = event.get("request")
    if isinstance(request, dict):
        for key in list(request):
            if str(key).lower() in _REQUEST_BODY_KEYS:
                request.pop(key, None)
        if "headers" in request:
            request["headers"] = _drop_authorization(request.get("headers"))
    _scrub_monitoring_inplace(event)
    return event


def _redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY.search(key) and value not in (None, "", 0, False):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact(value)
    return value


class SecretRedactionFilter(logging.Filter):
    """Redacts the rendered message of every record (plain-text and JSON handlers)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True
        cleaned = redact(rendered)
        if cleaned != rendered:
            record.msg, record.args = cleaned, None
        return True


class JsonFormatter(logging.Formatter):
    """Emit log records as one JSON object per line (for production log aggregation)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_ctx.get()
        if rid:
            payload["request_id"] = rid
        wid = workspace_id_ctx.get()
        if wid is not None:
            payload["workspace_id"] = wid
        for k, v in vars(record).items():
            if k not in _RESERVED and v is not None:
                payload[k] = _redact_value(k, v)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO", use_json: bool = False) -> None:
    """Configure root/app log level and, if use_json, JSON formatter to stdout."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        root.addHandler(handler)
    for h in root.handlers:
        if not any(isinstance(f, SecretRedactionFilter) for f in h.filters):
            h.addFilter(SecretRedactionFilter())
        if use_json:
            h.setFormatter(JsonFormatter())
    # Ensure app loggers use root config
    logging.getLogger("app").setLevel(getattr(logging, log_level.upper(), logging.INFO))
