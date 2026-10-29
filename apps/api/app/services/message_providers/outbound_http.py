"""Outbound HTTP seam for Slack and Gmail.

This is not TC-07-009. It only enforces a fixed hostname allowlist, HTTPS on
port 443, a timeout, a response size cap, and no redirect following. It does
not resolve DNS, block rebinding, or scan private addresses beyond rejecting
hosts that are not on the allowlist.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

# Fixed allowlist: Slack Web API and the Google API hosts used by Gmail.
ALLOWED_HOSTS = frozenset(
    {
        "slack.com",
        "gmail.googleapis.com",
        "www.googleapis.com",
        "oauth2.googleapis.com",
    }
)

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 1_048_576


class OutboundHttpDenied(Exception):
    """The URL is outside the message-provider allowlist. The call was not sent."""

    def __init__(self, reason: str, host: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.host = host


class ProviderResponseTooLarge(Exception):
    """The decoded provider response exceeded the allowed body size."""

    def __init__(self, status_code: int):
        super().__init__("The provider response exceeded the size limit.")
        self.status_code = status_code


class OutboundHttpSeam:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.timeout = timeout
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        content: bytes | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        self.assert_allowed(url)
        with self._client.stream(
            method,
            url,
            headers=headers,
            content=content,
            params=params,
        ) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                # Measure decoded bytes, independent of Content-Length. Check
                # before retaining the chunk and never consume the next one.
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ProviderResponseTooLarge(response.status_code)
                body.extend(chunk)

            # The content has already been decoded. Install the original
            # headers after constructing the buffered response so HTTPX does
            # not try to decompress the same bytes for a second time.
            buffered = httpx.Response(
                response.status_code,
                content=bytes(body),
                request=response.request,
                extensions=response.extensions,
                history=response.history,
                default_encoding=response.default_encoding,
            )
            buffered.headers = response.headers.copy()
            return buffered

    @staticmethod
    def assert_allowed(url: str) -> None:
        try:
            parts = urlsplit(url)
        except ValueError as exc:
            raise OutboundHttpDenied("URL is not allowed") from exc
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme != "https":
            raise OutboundHttpDenied("only https is allowed for message providers", host or None)
        if not host or host not in ALLOWED_HOSTS:
            raise OutboundHttpDenied("host is not in the message-provider allowlist", host or None)
        if parts.port not in (None, 443):
            raise OutboundHttpDenied("only port 443 is allowed", host)
        if parts.username or parts.password:
            raise OutboundHttpDenied("URL userinfo is not allowed", host)
