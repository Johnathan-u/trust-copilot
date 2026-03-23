"""Structured logging: JSON to stdout in production, level from LOG_LEVEL."""

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# Request-scoped context (set by middleware)
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
workspace_id_ctx: ContextVar[int | None] = ContextVar("workspace_id", default=None)


# Standard LogRecord attributes to skip when merging extra
_RESERVED = frozenset(
    {
        "name", "msg", "args", "created", "filename", "funcName", "levelname", "levelno",
        "lineno", "module", "msecs", "pathname", "process", "processName", "relativeCreated",
        "stack_info", "exc_info", "exc_text", "thread", "threadName", "message", "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Emit log records as one JSON object per line (for production log aggregation)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_ctx.get()
        if rid:
            payload["request_id"] = rid
        wid = workspace_id_ctx.get()
        if wid is not None:
            payload["workspace_id"] = wid
        for k, v in vars(record).items():
            if k not in _RESERVED and v is not None:
                payload[k] = v
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(log_level: str = "INFO", use_json: bool = False) -> None:
    """Configure root/app log level and, if use_json, JSON formatter to stdout."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        root.addHandler(handler)
    if use_json:
        for h in root.handlers:
            h.setFormatter(JsonFormatter())
    # Ensure app loggers use root config
    logging.getLogger("app").setLevel(getattr(logging, log_level.upper(), logging.INFO))
