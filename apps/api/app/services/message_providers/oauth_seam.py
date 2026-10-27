"""Named seam for browser-bound OAuth state and PKCE.

TC-05-004 is not implemented. This seam does not mint state, a nonce, or a
PKCE verifier, and it does not exchange an authorization code or link
identities. Slack install (TC-19-002) and Gmail OAuth (TC-19-005) stay on
their own tickets. Connect routes still accept a pasted token.
"""

from __future__ import annotations

from app.services.message_providers.errors import not_implemented_result


class OAuthStatePkceSeam:
    def exchange_code(
        self,
        provider: str,
        code: str,
        verifier: str | None = None,
        state: str | None = None,
    ) -> dict:
        del code, verifier, state
        ticket = "TC-05-004; TC-19-002" if provider == "slack" else "TC-05-004; TC-19-005"
        return not_implemented_result(provider, "oauth.exchange_code", ticket)

    def begin_authorization(self, provider: str) -> dict:
        ticket = "TC-05-004; TC-19-002" if provider == "slack" else "TC-05-004; TC-19-005"
        return not_implemented_result(provider, "oauth.begin_authorization", ticket)
