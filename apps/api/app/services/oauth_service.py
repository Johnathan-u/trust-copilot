"""OAuth 2.0 token exchange and userinfo (ENT-201). Uses httpx."""

import base64
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_JWKS_URL = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
MICROSOFT_SCOPE = "openid profile email"

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def google_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": get_settings().oauth_google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def microsoft_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": get_settings().oauth_microsoft_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": MICROSOFT_SCOPE,
        "state": state,
        "response_mode": "query",
    }
    return f"{MICROSOFT_AUTH_URL}?{urlencode(params)}"


def github_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": get_settings().oauth_github_client_id,
        "redirect_uri": redirect_uri,
        "scope": "user:email read:user",
        "state": state,
    }
    return f"{GITHUB_AUTH_URL}?{urlencode(params)}"


async def github_exchange_code(code: str, redirect_uri: str) -> dict | None:
    """Exchange code for token and return userinfo (id, email, name). Fetches primary email if not in /user."""
    data = {
        "client_id": get_settings().oauth_github_client_id,
        "client_secret": get_settings().oauth_github_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            GITHUB_TOKEN_URL,
            data=data,
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            return None
        tok = r.json()
        access_token = tok.get("access_token")
        if not access_token:
            return None
        ui = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        if ui.status_code != 200:
            return None
        info = ui.json()
        email = (info.get("email") or "").strip().lower() or None
        email_verified = False
        if not email:
            em_r = await client.get(
                GITHUB_EMAILS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if em_r.status_code == 200:
                for e in em_r.json():
                    if e.get("primary") and e.get("email"):
                        email = e["email"].strip().lower()
                        email_verified = bool(e.get("verified"))
                        break
                if not email and em_r.json():
                    first = em_r.json()[0]
                    email = first.get("email", "").strip().lower() or None
                    email_verified = bool(first.get("verified"))
        else:
            em_r = await client.get(
                GITHUB_EMAILS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if em_r.status_code == 200:
                for e in em_r.json():
                    if (e.get("email") or "").strip().lower() == email:
                        email_verified = bool(e.get("verified"))
                        break
        return {
            "provider_user_id": str(info.get("id", "")),
            "email": email,
            "name": (info.get("name") or "").strip() or None,
            "email_verified": email_verified,
        }


def _redact(s: str | None, show_tail: int = 0) -> str:
    """Redact string for logging; optionally show last N chars."""
    if not s:
        return "(empty)"
    if len(s) <= show_tail:
        return "***"
    return "*" * (len(s) - show_tail) + s[-show_tail:] if show_tail else "***"


async def google_exchange_code(code: str, redirect_uri: str) -> dict | None:
    """Exchange code for tokens and return userinfo."""
    data = {
        "client_id": get_settings().oauth_google_client_id,
        "client_secret": get_settings().oauth_google_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(GOOGLE_TOKEN_URL, data=data, headers={"Accept": "application/json"})
        logger.info(
            "oauth_google token_exchange status=%s has_body=%s",
            r.status_code,
            bool(r.text),
            extra={"step": "google_token_exchange"},
        )
        if r.status_code != 200:
            return None
        tok = r.json()
        access_token = tok.get("access_token")
        if not access_token:
            logger.warning(
                "oauth_google token response missing access_token keys=%s", list(tok.keys())
            )
            return None
        ui = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        logger.info(
            "oauth_google userinfo status=%s",
            ui.status_code,
            extra={"step": "google_userinfo"},
        )
        if ui.status_code != 200:
            return None
        info = ui.json()
        # Prefer "id" (v2 userinfo), fall back to "sub" (OpenID Connect)
        raw_id = info.get("id") or info.get("sub")
        provider_user_id = str(raw_id).strip() if raw_id is not None else ""
        if not provider_user_id:
            logger.warning(
                "oauth_google profile missing both id and sub; keys=%s",
                list(info.keys()),
                extra={"step": "google_profile_missing_id"},
            )
            return None
        email = (info.get("email") or "").strip().lower() or None
        name = (info.get("name") or "").strip() or None
        logger.info(
            "oauth_google profile provider_user_id=%s email=%s name_len=%s",
            _redact(provider_user_id, 4),
            _redact(email, 3) if email else "(missing)",
            len(name) if name else 0,
            extra={"step": "google_profile_parsed"},
        )
        return {
            "provider_user_id": provider_user_id,
            "email": email,
            "name": name,
            "email_verified": bool(info.get("verified_email")),
        }


def _b64url_decode(segment: str) -> bytes:
    padding_chars = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding_chars)


def _b64url_int(segment: str) -> int:
    raw = _b64url_decode(segment)
    return int.from_bytes(raw, "big")


def _claim_is_true(value: object) -> bool:
    if value is True or value == 1:
        return True
    return isinstance(value, str) and value.strip().lower() in {"true", "1"}


async def _microsoft_identity_from_id_token(
    client: httpx.AsyncClient, id_token: str
) -> dict | None:
    """Trust a Microsoft email only when a validated id_token has xms_edov.

    Graph ``mail`` and ``userPrincipalName`` are not used. The identity key is
    the tenant id plus the object id.
    """
    parts = (id_token or "").split(".")
    if len(parts) != 3:
        return None
    try:
        header = json.loads(_b64url_decode(parts[0]))
        if header.get("alg") != "RS256" or not header.get("kid"):
            return None
        jwks = await client.get(MICROSOFT_JWKS_URL)
        if jwks.status_code != 200:
            return None
        keys = jwks.json().get("keys") or []
        jwk = next((item for item in keys if item.get("kid") == header["kid"]), None)
        if not jwk or not jwk.get("n") or not jwk.get("e"):
            return None
        public = RSAPublicNumbers(_b64url_int(jwk["e"]), _b64url_int(jwk["n"])).public_key()
        public.verify(
            _b64url_decode(parts[2]),
            f"{parts[0]}.{parts[1]}".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        claims = json.loads(_b64url_decode(parts[1]))
    except (InvalidSignature, ValueError, json.JSONDecodeError, KeyError, TypeError):
        return None
    now = int(time.time())
    try:
        exp = int(claims.get("exp"))
    except (TypeError, ValueError):
        return None
    if exp < now - 120:
        return None
    tid = str(claims.get("tid") or "").strip()
    oid = str(claims.get("oid") or "").strip()
    if not tid or not oid:
        return None
    issuer = f"https://login.microsoftonline.com/{tid}/v2.0"
    if claims.get("iss") != issuer:
        return None
    audience = claims.get("aud")
    client_id = get_settings().oauth_microsoft_client_id
    audiences = audience if isinstance(audience, list) else [audience]
    if not client_id or client_id not in audiences:
        return None
    verified = _claim_is_true(claims.get("xms_edov"))
    email = None
    if verified:
        candidate = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
        if "@" in candidate:
            email = candidate
        else:
            verified = False
    name = (claims.get("name") or "").strip() or None
    return {
        "provider_user_id": f"{tid}:{oid}",
        "email": email,
        "name": name,
        "email_verified": verified,
    }


async def microsoft_exchange_code(code: str, redirect_uri: str) -> dict | None:
    """Exchange a Microsoft code. Email is taken only from a validated id_token."""
    data = {
        "client_id": get_settings().oauth_microsoft_client_id,
        "client_secret": get_settings().oauth_microsoft_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "scope": MICROSOFT_SCOPE,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            MICROSOFT_TOKEN_URL, data=data, headers={"Accept": "application/json"}
        )
        if r.status_code != 200:
            return None
        tok = r.json()
        access_token = tok.get("access_token")
        if not access_token:
            return None
        identity = None
        if tok.get("id_token"):
            identity = await _microsoft_identity_from_id_token(client, tok["id_token"])
        if identity and identity.get("email_verified"):
            return identity
        ui = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$select": "id,displayName"},
        )
        graph_id = ""
        graph_name = None
        if ui.status_code == 200:
            info = ui.json()
            graph_id = str(info.get("id") or "")
            graph_name = (info.get("displayName") or "").strip() or None
        provider_user_id = (identity or {}).get("provider_user_id") or graph_id
        if not provider_user_id:
            return None
        return {
            "provider_user_id": provider_user_id,
            "email": None,
            "name": (identity or {}).get("name") or graph_name,
            "email_verified": False,
        }


def generate_state() -> str:
    return secrets.token_urlsafe(32)
