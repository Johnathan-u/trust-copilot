"""OAuth 2.0 token exchange and userinfo (ENT-201). Uses httpx."""

import logging
import secrets
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
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
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github.v3+json"},
        )
        if ui.status_code != 200:
            return None
        info = ui.json()
        email = (info.get("email") or "").strip().lower() or None
        email_verified = False
        if not email:
            em_r = await client.get(
                GITHUB_EMAILS_URL,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github.v3+json"},
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
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github.v3+json"},
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
            logger.warning("oauth_google token response missing access_token keys=%s", list(tok.keys()))
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


async def microsoft_exchange_code(code: str, redirect_uri: str) -> dict | None:
    """Exchange code for tokens and return userinfo from Microsoft Graph."""
    data = {
        "client_id": get_settings().oauth_microsoft_client_id,
        "client_secret": get_settings().oauth_microsoft_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "scope": MICROSOFT_SCOPE,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(MICROSOFT_TOKEN_URL, data=data, headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None
        tok = r.json()
        access_token = tok.get("access_token")
        if not access_token:
            return None
        ui = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$select": "id,mail,userPrincipalName,displayName"},
        )
        if ui.status_code != 200:
            return None
        info = ui.json()
        mail = (info.get("mail") or "").strip().lower() or None
        upn = (info.get("userPrincipalName") or "").strip().lower() or None
        email = mail or upn
        return {
            "provider_user_id": str(info.get("id", "")),
            "email": email,
            "name": (info.get("displayName") or "").strip() or None,
            "email_verified": bool(mail),
        }


def generate_state() -> str:
    return secrets.token_urlsafe(32)
