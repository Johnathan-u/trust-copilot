"""OIDC SSO (ENT-203) and id.me (ENT-205) - server-side discovery, token exchange, userinfo."""

from urllib.parse import urlencode

import httpx

from app.core.config import get_settings

# Cache for OIDC discovery (issuer -> openid config)
_oidc_config_cache: dict[str, dict] = {}


def _oidc_well_known(issuer_url: str) -> str:
    base = (issuer_url or "").rstrip("/")
    return f"{base}/.well-known/openid-configuration"


async def oidc_discover(issuer_url: str) -> dict | None:
    """Fetch and cache OIDC discovery document."""
    if not issuer_url:
        return None
    key = issuer_url.rstrip("/")
    if key in _oidc_config_cache:
        return _oidc_config_cache[key]
    url = _oidc_well_known(issuer_url)
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        doc = r.json()
        _oidc_config_cache[key] = doc
        return doc


def oidc_authorize_url(state: str, redirect_uri: str, discovery: dict, scope: str) -> str | None:
    """Build authorization URL from discovery."""
    auth_endpoint = discovery.get("authorization_endpoint")
    if not auth_endpoint:
        return None
    s = get_settings()
    client_id = s.oidc_client_id
    if not client_id:
        return None
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope or s.oidc_scope,
        "state": state,
    }
    return f"{auth_endpoint}?{urlencode(params)}"


async def oidc_exchange_code(
    code: str,
    redirect_uri: str,
    discovery: dict,
) -> dict | None:
    """Exchange authorization code for tokens and return userinfo (sub, email, name, etc.)."""
    token_endpoint = discovery.get("token_endpoint")
    userinfo_endpoint = discovery.get("userinfo_endpoint")
    if not token_endpoint:
        return None
    s = get_settings()
    data = {
        "client_id": s.oidc_client_id,
        "client_secret": s.oidc_client_secret or "",
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            token_endpoint,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            return None
        tok = r.json()
        access_token = tok.get("access_token")
        if not access_token:
            return None
        if not userinfo_endpoint:
            # Some IdPs put email in id_token; we don't decode JWT here, so require userinfo
            return None
        ui = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if ui.status_code != 200:
            return None
        info = ui.json()
        sub = info.get("sub")
        if not sub:
            return None
        email = (info.get("email") or info.get("preferred_username") or "").strip().lower() or None
        name = (info.get("name") or info.get("given_name") or "").strip() or None
        return {
            "provider_user_id": str(sub),
            "email": email,
            "name": name,
            "email_verified": bool(info.get("email_verified")),
            "raw_claims": {k: v for k, v in info.items() if k in ("sub", "email", "name", "preferred_username", "groups")},
        }


# --- id.me (ENT-205, ENT-206) ---
# id.me uses OAuth 2.0 / OIDC; documented endpoints. Static redirect URI required (no wildcards).

IDME_SANDBOX_AUTH = "https://api.id.me/oauth/authorize"
IDME_SANDBOX_TOKEN = "https://api.id.me/oauth/token"
IDME_SANDBOX_USERINFO = "https://api.id.me/api/public/v3/user_info"
# Production: https://api.id.me/oauth/authorize (same host; env can override if needed)


def idme_authorize_url(redirect_uri: str, state: str) -> str | None:
    """Build id.me authorization URL. ENT-206: redirect_uri must be exact (static)."""
    s = get_settings()
    if not s.idme_client_id:
        return None
    params = {
        "client_id": s.idme_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
    }
    return f"{IDME_SANDBOX_AUTH}?{urlencode(params)}"


async def idme_exchange_code(code: str, redirect_uri: str) -> dict | None:
    """Exchange code for id.me token and fetch user_info. Server-side only; minimal claim storage."""
    s = get_settings()
    if not s.idme_client_id or not s.idme_client_secret:
        return None
    data = {
        "client_id": s.idme_client_id,
        "client_secret": s.idme_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            IDME_SANDBOX_TOKEN,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            return None
        tok = r.json()
        access_token = tok.get("access_token")
        if not access_token:
            return None
        ui = await client.get(
            IDME_SANDBOX_USERINFO,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if ui.status_code != 200:
            return None
        info = ui.json()
        # Minimal claims: sub (uuid), email, name
        sub = info.get("sub") or info.get("uuid") or info.get("id")
        if not sub:
            return None
        email = (info.get("email") or "").strip().lower() or None
        name = (info.get("name") or info.get("display_name") or "").strip() or None
        return {
            "provider_user_id": str(sub),
            "email": email,
            "name": name,
            "email_verified": bool(info.get("email_verified", info.get("verified"))),
        }
