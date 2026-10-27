"""Slack and Gmail provider selection for TC-19-001.

Prerequisite tickets are not implemented. Named seams live beside this package:

- ``outbound_http.OutboundHttpSeam`` stands in for TC-07-009 (allowlist, timeout, size, no redirects).
- ``retry_seam.BoundedRetrySeam`` stands in for TC-10-002 (error class and bounded attempts).
- ``oauth_seam.OAuthStatePkceSeam`` stands in for TC-05-004 (no state, nonce, or PKCE exchange).
"""

from app.services.message_providers.errors import (
    DEV_STUB_LABEL,
    DEV_STUB_MODE,
    HTTP_MODE,
    failure_result,
    is_provider_failure,
    not_implemented_result,
    public_error_detail,
)
from app.services.message_providers.selection import (
    MessageProviderConfigurationError,
    MessageProviderSelection,
    assert_message_provider_preflight,
    delivery_accepted,
    message_provider_preflight,
    resolve_message_provider_selection,
)

__all__ = [
    "DEV_STUB_LABEL",
    "DEV_STUB_MODE",
    "HTTP_MODE",
    "MessageProviderConfigurationError",
    "MessageProviderSelection",
    "assert_message_provider_preflight",
    "delivery_accepted",
    "failure_result",
    "is_provider_failure",
    "message_provider_preflight",
    "not_implemented_result",
    "public_error_detail",
    "resolve_message_provider_selection",
]
