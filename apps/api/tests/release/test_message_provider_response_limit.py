"""Provider response limits use synthetic streams and make no network calls."""

from __future__ import annotations

import gzip
import tracemalloc
import zlib

import httpx
import pytest

from app.services.message_providers.http_client import MessageProviderHttp
from app.services.message_providers.outbound_http import OutboundHttpSeam

pytestmark = pytest.mark.unit
LIMIT = 1_048_576


class TrackedStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes | Exception]):
        self.chunks = chunks
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.consumed += 1
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


def call_stream(stream, *, headers=None, provider="slack", status=200):
    calls = []
    attempts = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers=headers, stream=stream)

    client = MessageProviderHttp(transport=httpx.MockTransport(handler))
    try:
        result = client.call(
            "GET",
            "https://slack.com/api/auth.test"
            if provider == "slack"
            else "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            provider=provider,
            on_attempt=lambda result, retry: attempts.append((result, retry)),
        )
    finally:
        client.close()
    return result, calls, attempts


@pytest.mark.parametrize("length", [None, "1", "999999999"])
@pytest.mark.parametrize("status", [200, 429, 503])
def test_oversized_stream_stops_before_later_chunks_and_does_not_retry(length, status):
    # Removing the transport limit would consume the third chunk before rejection.
    stream = TrackedStream([b"x" * LIMIT, b"x", b"must not be consumed"])
    headers = {} if length is None else {"Content-Length": length}
    result, calls, attempts = call_stream(stream, headers=headers, status=status)

    assert stream.consumed == (0 if length == "999999999" else 2)
    assert stream.closed
    assert len(calls) == 1
    assert not result.ok
    assert result.status_code == status
    assert result.provider_error == "response_too_large"
    assert result.error_code == "unknown"
    assert result.body == {}
    assert result.retryable is False
    assert result.attempts == 1
    assert result.exhausted is False
    assert attempts == [(result, False)]


@pytest.mark.parametrize("provider", ["slack", "gmail"])
def test_exact_limit_json_succeeds_and_closes(provider):
    body = b'{"ok":true,"value":"' + b"x" * (LIMIT - 22) + b'"}'
    assert len(body) == LIMIT
    stream = TrackedStream([body[:500_000], body[500_000:]])
    result, calls, _ = call_stream(stream, provider=provider)

    assert result.ok
    assert result.body["ok"] is True
    assert len(result.body["value"]) == LIMIT - 22
    assert len(calls) == 1
    assert stream.closed


def test_compressed_decoded_limit_stops_before_later_chunks():
    compressor = zlib.compressobj(wbits=31)
    first = compressor.compress(b"x" * LIMIT) + compressor.flush(zlib.Z_SYNC_FLUSH)
    second = compressor.compress(b"x") + compressor.flush(zlib.Z_SYNC_FLUSH)
    third = compressor.compress(b"must not be consumed") + compressor.flush()
    stream = TrackedStream([first, second, third])
    result, calls, _ = call_stream(
        stream,
        headers={"Content-Encoding": "gzip", "Content-Length": str(len(first + second + third))},
    )

    assert stream.consumed == 2
    assert stream.closed
    assert len(calls) == 1
    assert result.provider_error == "response_too_large"
    assert result.retryable is False
    assert result.body == {}


def test_small_compressed_json_remains_readable():
    stream = TrackedStream([gzip.compress(b'{"ok":true,"team_id":"T123"}')])
    result, _, _ = call_stream(stream, headers={"Content-Encoding": "gzip"})
    assert result.ok
    assert result.body == {"ok": True, "team_id": "T123"}
    assert stream.closed


def test_stream_closes_when_read_fails():
    stream = TrackedStream([b"{", httpx.ReadError("synthetic stream failure")])
    seam = OutboundHttpSeam(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    )
    try:
        with pytest.raises(httpx.ReadError):
            seam.request("GET", "https://slack.com/api/auth.test")
    finally:
        seam.close()
    assert stream.closed


def test_small_success_preserves_response_metadata():
    stream = TrackedStream([b'{"ok":true}'])
    seam = OutboundHttpSeam(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"X-Request-Id": "fixture"}, stream=stream)
        )
    )
    try:
        response = seam.request("GET", "https://slack.com/api/auth.test")
        assert response.status_code == 200
        assert response.headers["X-Request-Id"] == "fixture"
        assert response.request.url == "https://slack.com/api/auth.test"
        assert response.json() == {"ok": True}
        assert response.is_closed
    finally:
        seam.close()
    assert stream.closed


def compressed_zeros(size):
    compressor = zlib.compressobj(wbits=31)
    pieces = [compressor.compress(b"\0" * 65_536) for _ in range(size // 65_536)]
    return b"".join(pieces) + compressor.flush()


@pytest.mark.parametrize("nested", [False, True])
def test_compressed_bomb_is_rejected_with_bounded_allocation(nested):
    payload = compressed_zeros(32 * 1024 * 1024)
    if nested:
        payload = gzip.compress(payload)
    stream = TrackedStream([payload, b"unread tail"])
    tracemalloc.start()
    try:
        result, calls, _ = call_stream(
            stream, headers={"Content-Encoding": "gzip, gzip" if nested else "gzip"}
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, peak
    assert result.provider_error == "response_too_large"
    assert result.retryable is False
    assert len(calls) == 1
    assert stream.consumed == (0 if nested else 1)
    assert stream.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_exact_limit_compressed_json_succeeds(encoding):
    body = b'{"ok":true,"value":"' + b"x" * (LIMIT - 22) + b'"}'
    payload = gzip.compress(body) if encoding == "gzip" else zlib.compress(body)
    stream = TrackedStream([payload[:11], payload[11:]])
    result, _, _ = call_stream(stream, headers={"Content-Encoding": encoding})
    assert result.ok
    assert len(result.body["value"]) == LIMIT - 22
    assert stream.closed


@pytest.mark.parametrize("encoding", ["br", "gzip, identity", "identity, identity"])
def test_unsupported_or_multiple_encoding_is_rejected_without_reading(encoding):
    stream = TrackedStream([b"must not read"])
    result, calls, _ = call_stream(stream, headers={"Content-Encoding": encoding})
    assert result.provider_error == "response_too_large"
    assert result.retryable is False
    assert len(calls) == 1
    assert stream.consumed == 0
    assert stream.closed


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_is_classified_without_reading_body(status):
    stream = TrackedStream([b"x" * (LIMIT + 1)])
    result, calls, _ = call_stream(
        stream,
        status=status,
        headers={"Location": "https://untrusted.example/", "Content-Length": str(LIMIT + 1)},
    )
    assert result.provider_error == "redirect_blocked"
    assert result.status_code == status
    assert result.retryable is False
    assert len(calls) == 1
    assert stream.consumed == 0
    assert stream.closed


def test_truncated_gzip_cannot_be_accepted_as_success():
    # Missing the gzip checksum/size trailer still yields valid JSON to HTTPX.
    stream = TrackedStream([gzip.compress(b'{"ok":true}')[:-8]])
    result, calls, _ = call_stream(stream, headers={"Content-Encoding": "gzip"})
    assert not result.ok
    assert result.retryable is False
    assert len(calls) == 1
    assert stream.closed
