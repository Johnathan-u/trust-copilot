"""TC-02-OAPI-001: published OpenAPI must not contain internal ticket ids.

The pattern is the ticket forms ``PREFIX-NN`` / ``PREFIX-NNn`` and ``TC-NN-``.
``SHA-``, ``UTF-`` and ``ISO-`` are excluded so standards tokens such as
SHA-256, UTF-8 and ISO-8601 are not treated as tickets. UTF-8 has a one-digit
suffix and ISO-8601 has four digits, so those already fall outside
``\\d{2,3}``; the prefix exclusion is what keeps SHA-256 out.
"""

import re

import pytest

# Ticket ids are 2–5 uppercase letters, a hyphen, and 2–3 digits, with an
# optional trailing lowercase letter (for example AUTH-207 or REV-07). SHA-256
# matches that shape, so those three standards prefixes are carved out of the
# expression itself rather than listed as allowed hits.
TICKET_ID = re.compile(r"\b(?!SHA-|UTF-|ISO-)[A-Z]{2,5}-\d{2,3}[a-z]?\b|\bTC-\d{2}-")

# Any upper-case identifier that contains an underscore. A suffix list missed
# names such as APP_ENV, S3_BUCKET and RATE_LIMIT_RPM_PER_IP. The published
# OpenAPI scan found no matches, so there is no exclusion list.
ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]*[A-Z0-9]\b")

_TEXT_KEYS = ("summary", "description")


def _matches(text: str, pattern: re.Pattern[str] = TICKET_ID) -> list[str]:
    return [match.group(0) for match in pattern.finditer(text or "")]


def _operation_hits(spec: dict, pattern: re.Pattern[str] = TICKET_ID) -> list[str]:
    found: list[str] = []
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for key in _TEXT_KEYS:
            for token in _matches(item.get(key) or "", pattern):
                found.append(f"{path} {key} {token}")
        for method, operation in item.items():
            if not isinstance(operation, dict) or method in {
                "parameters",
                "summary",
                "description",
            }:
                continue
            if method.startswith("x-"):
                continue
            label = operation.get("operationId") or f"{method.upper()} {path}"
            for key in _TEXT_KEYS:
                for token in _matches(operation.get(key) or "", pattern):
                    found.append(f"{label} {key} {token}")
            for param in operation.get("parameters") or []:
                if not isinstance(param, dict):
                    continue
                name = param.get("name") or "?"
                for key in _TEXT_KEYS:
                    for token in _matches(param.get(key) or "", pattern):
                        found.append(f"{label} parameter {name} {key} {token}")
            body = operation.get("requestBody")
            if isinstance(body, dict):
                for token in _matches(body.get("description") or "", pattern):
                    found.append(f"{label} requestBody description {token}")
    return found


def _schema_hits(spec: dict, pattern: re.Pattern[str] = TICKET_ID) -> list[str]:
    found: list[str] = []

    def walk(node, location: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _TEXT_KEYS and isinstance(value, str):
                    for token in _matches(value, pattern):
                        found.append(f"{location} {key} {token}")
                else:
                    walk(value, f"{location}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{location}[{index}]")

    walk(spec.get("components", {}).get("schemas", {}), "schema")
    return found


def test_published_openapi_has_no_ticket_ids():
    """Path text, operation text, parameters and schema descriptions stay free of ticket ids."""
    from app.main import app

    spec = app.openapi()
    hits = _operation_hits(spec) + _schema_hits(spec)
    assert not hits, "ticket ids in published OpenAPI:\n" + "\n".join(hits)


def test_published_openapi_has_no_env_names():
    """The same published text must not name environment variables."""
    from app.main import app

    spec = app.openapi()
    hits = _operation_hits(spec, ENV_NAME) + _schema_hits(spec, ENV_NAME)
    assert not hits, "env names in published OpenAPI:\n" + "\n".join(hits)


@pytest.mark.parametrize("sample", ["SHA-256", "UTF-8", "ISO-8601", "hash with SHA-256 and UTF-8"])
def test_ticket_pattern_does_not_match_standards_tokens(sample):
    assert TICKET_ID.search(sample) is None


@pytest.mark.parametrize(
    "sample",
    [
        "waits for READINESS_TIMEOUT_SEC",
        "stale after WORKER_HEARTBEAT_STALE_SEC",
        "when OPENAI_API_KEY is configured",
        "capped by RATE_LIMIT_RPM_PER_IP",
        "stored in S3_BUCKET",
        "selected by APP_ENV",
    ],
)
def test_env_pattern_matches_uppercase_names_with_an_underscore(sample):
    assert ENV_NAME.search(sample)


@pytest.mark.parametrize("sample", ["ordinary words", "SHA-256", "UTF-8"])
def test_env_pattern_ignores_ordinary_words_and_standards_tokens(sample):
    assert ENV_NAME.search(sample) is None
