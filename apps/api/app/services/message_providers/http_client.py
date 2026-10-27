"""Shared HTTP caller used by the Slack and Gmail providers."""

from __future__ import annotations

import httpx

from app.services.message_providers.outbound_http import DEFAULT_TIMEOUT_SECONDS, OutboundHttpSeam
from app.services.message_providers.retry_seam import (
    DEFAULT_MAX_ATTEMPTS,
    BoundedRetrySeam,
    ProviderCallResult,
)


class MessageProviderHttp:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        sleeper=None,
    ) -> None:
        self.seam = OutboundHttpSeam(transport=transport, timeout=timeout)
        self.retry = BoundedRetrySeam(max_attempts=max_attempts, sleeper=sleeper)

    def close(self) -> None:
        self.seam.close()

    def call(
        self,
        method: str,
        url: str,
        *,
        provider: str,
        headers: dict | None = None,
        content: bytes | None = None,
        params: dict | None = None,
        on_attempt=None,
    ) -> ProviderCallResult:
        def attempt() -> httpx.Response:
            return self.seam.request(method, url, headers=headers, content=content, params=params)

        return self.retry.execute(attempt, provider=provider, on_attempt=on_attempt)
