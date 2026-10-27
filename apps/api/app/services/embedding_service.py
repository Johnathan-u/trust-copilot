"""Generate embeddings and persist to chunks (DOC-08). Timeout and retry for transient failures."""

import logging
import threading
import time
from typing import Callable, Optional

from app.core.config import get_settings
from app.core.metrics import OPENAI_EMBEDDING_FAILURES_TOTAL
from app.services.model_outcomes import ModelFailure, classify_provider_exception

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
OPENAI_TIMEOUT_SECONDS = 60
OPENAI_MAX_RETRIES = 2
EMBED_RETRY_BASE_SECONDS = 1.0
EMBED_RETRY_MAX_SECONDS = 8.0

# TC-10-002: the last provider error swallowed by embed_texts() in this thread, so the indexer can classify it
# (retryable vs terminal) instead of reporting a generic failure.
_last_error = threading.local()


def reset_last_embed_error() -> None:
    _last_error.exc = None


def last_embed_error() -> Optional[Exception]:
    return getattr(_last_error, "exc", None)


def _retry_sleep_seconds(attempt: int, e: Exception) -> float:
    """Bounded exponential backoff with jitter for the in-call retry (TC-10-002)."""
    from app.core.job_errors import backoff_delay, retry_after_seconds

    return backoff_delay(
        attempt + 1,
        base=EMBED_RETRY_BASE_SECONDS,
        cap=EMBED_RETRY_MAX_SECONDS,
        retry_after=retry_after_seconds(e),
    )


_embed_client = None
_embed_client_key: str | None = None


def _get_embed_client(api_key: str):
    """Reuse a single OpenAI client for embedding calls (connection pooling)."""
    global _embed_client, _embed_client_key
    if _embed_client is not None and _embed_client_key == api_key:
        return _embed_client
    from openai import OpenAI

    _embed_client = OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS)
    _embed_client_key = api_key
    return _embed_client


def _is_transient_error(e: Exception) -> bool:
    """True if error is worth retrying (TC-10-002 classifier: 429, timeout, 5xx, connection)."""
    from app.core.job_errors import classify, is_retryable_code

    if is_retryable_code(classify(e)):
        return True
    msg = (getattr(e, "message", "") or str(e)).lower()
    return "timeout" in msg or "timed out" in msg


def embed_text(text: str) -> Optional[list[float]]:
    """Generate embedding for text via OpenAI. Returns None if no API key or error. Validates dimension on success. Timeout + retry on transient errors."""
    settings = get_settings()
    if not settings.openai_api_key or not text.strip():
        return None
    client = _get_embed_client(settings.openai_api_key)
    last_err: Optional[Exception] = None
    for attempt in range(OPENAI_MAX_RETRIES + 1):
        try:
            r = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text[:8000],
            )
            emb = r.data[0].embedding
            if emb is not None and len(emb) != EMBEDDING_DIM:
                raise ValueError(f"Embedding dimension {len(emb)} != required {EMBEDDING_DIM}")
            return emb
        except ValueError:
            raise
        except Exception as e:
            last_err = e
            OPENAI_EMBEDDING_FAILURES_TOTAL.inc()
            if attempt < OPENAI_MAX_RETRIES and _is_transient_error(e):
                sleep_sec = _retry_sleep_seconds(attempt, e)
                logger.warning(
                    "embed_text transient error (attempt %s), retry in %.1fs: %s",
                    attempt + 1,
                    sleep_sec,
                    classify_provider_exception(e).log_summary(),
                )
                time.sleep(sleep_sec)
            else:
                break
    logger.warning(
        "ALERT_OPENAI_FAILURE embed_text failed after %s attempts: %s",
        OPENAI_MAX_RETRIES + 1,
        classify_provider_exception(last_err).log_summary() if last_err is not None else None,
    )
    return None


def embed_texts(
    texts: list[str],
    on_failure: Optional[Callable[[ModelFailure], None]] = None,
) -> list[Optional[list[float]]]:
    """Batch embed texts. Returns list of embeddings (None for failed). Validates dimension for each; raises on mismatch. Timeout + retry on transient errors.

    TC-11-001: when the provider call fails, ``on_failure`` (if given) receives the typed
    :class:`ModelFailure` so callers can tell credentials/model failures apart from "no evidence".
    The return value is unchanged (all ``None``) for backward compatibility.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return [None] * len(texts)
    valid = [t.strip() for t in texts if t and t.strip()]
    if not valid:
        return [None] * len(texts)
    client = _get_embed_client(settings.openai_api_key)
    last_err: Optional[Exception] = None
    for attempt in range(OPENAI_MAX_RETRIES + 1):
        try:
            r = client.embeddings.create(model=EMBEDDING_MODEL, input=valid)
            emb_map = {}
            for d in r.data:
                emb = d.embedding
                if emb is not None and len(emb) != EMBEDDING_DIM:
                    raise ValueError(
                        f"Embedding at index {d.index} has dimension {len(emb)} != required {EMBEDDING_DIM}"
                    )
                emb_map[d.index] = emb
            out: list[Optional[list[float]]] = []
            idx = 0
            for t in texts:
                if t and t.strip():
                    out.append(emb_map.get(idx, None))
                    idx += 1
                else:
                    out.append(None)
            return out
        except ValueError:
            raise
        except Exception as e:
            last_err = e
            OPENAI_EMBEDDING_FAILURES_TOTAL.inc()
            if attempt < OPENAI_MAX_RETRIES and _is_transient_error(e):
                sleep_sec = _retry_sleep_seconds(attempt, e)
                logger.warning(
                    "embed_texts transient error (attempt %s), retry in %.1fs: %s",
                    attempt + 1,
                    sleep_sec,
                    classify_provider_exception(e).log_summary(),
                )
                time.sleep(sleep_sec)
            else:
                break
    logger.warning(
        "ALERT_OPENAI_FAILURE embed_texts failed after %s attempts: %s",
        OPENAI_MAX_RETRIES + 1,
        classify_provider_exception(last_err).log_summary() if last_err is not None else None,
    )
    if on_failure is not None and last_err is not None:
        on_failure(classify_provider_exception(last_err))
    _last_error.exc = last_err
    return [None] * len(texts)
