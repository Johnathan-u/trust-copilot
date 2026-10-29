"""Versioned key custody for session, OAuth-state, MFA and connector secrets.

Each purpose has its own keyring. When the purpose env var is unset, the
current key id is ``v0-legacy`` and the key is HKDF(SESSION_SECRET, purpose).
Ciphertext and signatures with no key id still use today's sha256(SESSION_SECRET)
derivation so existing rows and cookies stay readable.

Custody is versioned environment keyrings, not a KMS. CSRF itself checks
Origin/Referer and does not use a signing key; the oauth-state purpose covers
signed OAuth state.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

LEGACY_KID = "v0-legacy"
PURPOSES = ("session", "oauth_state", "mfa", "connector")
PURPOSE_ENV = {
    "session": "SESSION_KEYRING",
    "oauth_state": "OAUTH_STATE_KEYRING",
    "mfa": "MFA_KEYRING",
    "connector": "CONNECTOR_KEYRING",
}
_KID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_FERNET_PREFIX = "gAAAA"
REENROL_MARK = "reenrol"


class KeyErrorSafe(Exception):
    """Keyring or ciphertext failure. The message never includes key material or plaintext."""


class MfaReenrolRequired(KeyErrorSafe):
    """The stored MFA secret cannot be opened. The user must enrol again."""


@dataclass(frozen=True)
class KeyEntry:
    kid: str
    secret: str


@dataclass(frozen=True)
class Keyring:
    purpose: str
    current: KeyEntry
    retired: tuple[KeyEntry, ...]

    def find(self, kid: str) -> KeyEntry | None:
        if self.current.kid == kid:
            return self.current
        for entry in self.retired:
            if entry.kid == kid:
                return entry
        return None


def _session_secret(env: dict[str, str] | None = None) -> str:
    if env is not None:
        return env.get("SESSION_SECRET") or ""
    from app.core.session import get_session_secret

    return get_session_secret()


def _hkdf(secret: str, purpose: str, label: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"trust-copilot:{purpose}:{label}".encode(),
    ).derive(secret.encode())


def _legacy_sha256(secret: str) -> bytes:
    """Today's derivation: sha256(SESSION_SECRET), full 32-byte digest."""
    return hashlib.sha256(secret.encode()).digest()


def _parse_keyring(raw: str, purpose: str) -> tuple[KeyEntry, tuple[KeyEntry, ...]]:
    entries: list[KeyEntry] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise KeyErrorSafe(f"{PURPOSE_ENV[purpose]} entry is missing a key id")
        kid, secret = item.split(":", 1)
        kid = kid.strip()
        if not _KID_RE.match(kid):
            raise KeyErrorSafe(f"{PURPOSE_ENV[purpose]} has an invalid key id")
        if secret == "":
            raise KeyErrorSafe(f"{PURPOSE_ENV[purpose]} has an empty key")
        entries.append(KeyEntry(kid, secret))
    if not entries:
        raise KeyErrorSafe(f"{PURPOSE_ENV[purpose]} is empty")
    return entries[0], tuple(entries[1:])


def load_session_keyring() -> Keyring:
    return keyring_for("session")


def load_mfa_keyring() -> Keyring:
    return keyring_for("mfa")


def load_connector_keyring() -> Keyring:
    return keyring_for("connector")


def keyring_for(purpose: str, env: dict[str, str] | None = None) -> Keyring:
    if purpose not in PURPOSE_ENV:
        raise KeyErrorSafe("unknown key purpose")
    source = os.environ if env is None else env
    raw = (source.get(PURPOSE_ENV[purpose]) or "").strip()
    if not raw:
        secret = _session_secret(env)
        return Keyring(purpose, KeyEntry(LEGACY_KID, secret), ())
    current, retired = _parse_keyring(raw, purpose)
    return Keyring(purpose, current, retired)


def _material(entry: KeyEntry, purpose: str, *, legacy_hkdf: bool) -> bytes:
    if legacy_hkdf and entry.kid == LEGACY_KID:
        return _hkdf(entry.secret, purpose, LEGACY_KID)
    if entry.kid == LEGACY_KID and not legacy_hkdf:
        return _legacy_sha256(entry.secret)
    return _hkdf(entry.secret, purpose, entry.kid)


def _fernet(material: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(material))


def seal(purpose: str, plaintext: str, env: dict[str, str] | None = None) -> str:
    ring = keyring_for(purpose, env)
    explicit = bool((os.environ if env is None else env).get(PURPOSE_ENV[purpose], "").strip())
    material = _material(ring.current, purpose, legacy_hkdf=not explicit)
    token = _fernet(material).encrypt(plaintext.encode()).decode()
    sealed = f"{ring.current.kid}.{token}"
    if purpose == "mfa" and len(sealed) > 512:
        raise KeyErrorSafe("mfa ciphertext does not fit the totp column")
    return sealed


def stored_key_id(stored: str | None) -> str:
    """Key id embedded in a ciphertext, or ``unknown`` when there is none.

    The returned id matches the key-id grammar. The token itself is never returned.
    """
    if not isinstance(stored, str) or not stored:
        return "unknown"
    if stored.startswith(f"{REENROL_MARK}."):
        kid = stored.split(".", 1)[1]
    elif stored.startswith(_FERNET_PREFIX):
        return "unknown"
    elif "." in stored:
        kid = stored.split(".", 1)[0]
    else:
        return "unknown"
    if _KID_RE.fullmatch(kid):
        return kid
    return "unknown"


def open_sealed(purpose: str, stored: str, env: dict[str, str] | None = None) -> str:
    if stored.startswith(f"{REENROL_MARK}."):
        raise MfaReenrolRequired("mfa secret must be enrolled again")
    ring = keyring_for(purpose, env)
    session_secret = _session_secret(env)
    try:
        if stored.startswith(_FERNET_PREFIX):
            return _fernet(_legacy_sha256(session_secret)).decrypt(stored.encode()).decode()
        kid, token = stored.split(".", 1)
        entry = ring.find(kid)
        if entry is None:
            raise KeyErrorSafe("unknown key id")
        explicit = bool((os.environ if env is None else env).get(PURPOSE_ENV[purpose], "").strip())
        material = _material(entry, purpose, legacy_hkdf=not explicit or kid != LEGACY_KID)
        if not explicit and kid == LEGACY_KID:
            material = _hkdf(entry.secret, purpose, LEGACY_KID)
        return _fernet(material).decrypt(token.encode()).decode()
    except MfaReenrolRequired:
        raise
    except (InvalidToken, KeyErrorSafe, ValueError):
        raise KeyErrorSafe("ciphertext could not be opened") from None


def sign_with_purpose(purpose: str, data: str, env: dict[str, str] | None = None) -> str:
    ring = keyring_for(purpose, env)
    explicit = bool((os.environ if env is None else env).get(PURPOSE_ENV[purpose], "").strip())
    material = _material(ring.current, purpose, legacy_hkdf=not explicit)
    sig = hmac.new(material, data.encode(), "sha256").hexdigest()
    return f"{ring.current.kid}.{data}.{sig}"


def verify_with_purpose(
    purpose: str, token: str, *, accept_retired: bool, env: dict[str, str] | None = None
) -> str | None:
    """Return the signed payload when the current key matches.

    Retired keys are checked so a forged token is distinct from a retired one,
    but a retired key never returns the payload. Unprefixed tokens use today's
    raw SESSION_SECRET HMAC.
    """
    if not token or token.count(".") not in (1, 2):
        return None
    ring = keyring_for(purpose, env)
    session_secret = _session_secret(env)
    try:
        if token.count(".") == 1:
            data, sig = token.split(".", 1)
            expected = hmac.new(session_secret.encode(), data.encode(), "sha256").hexdigest()
            if hmac.compare_digest(sig, expected):
                return data
            return None
        kid, data, sig = token.split(".", 2)
        entry = ring.find(kid)
        if entry is None:
            return None
        explicit = bool((os.environ if env is None else env).get(PURPOSE_ENV[purpose], "").strip())
        material = _material(entry, purpose, legacy_hkdf=not explicit)
        if not explicit and kid == LEGACY_KID:
            material = _hkdf(entry.secret, purpose, LEGACY_KID)
        expected = hmac.new(material, data.encode(), "sha256").hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if kid != ring.current.kid and not accept_retired:
            return None
        return data
    except KeyErrorSafe:
        return None


def current_session_key_id(env: dict[str, str] | None = None) -> str:
    return keyring_for("session", env).current.kid


def retired_session_key_ids(env: dict[str, str] | None = None) -> tuple[str, ...]:
    ring = keyring_for("session", env)
    ids = [entry.kid for entry in ring.retired]
    if ring.current.kid != LEGACY_KID and LEGACY_KID not in ids:
        if not (os.environ if env is None else env).get(PURPOSE_ENV["session"], "").strip():
            return tuple(ids)
    return tuple(ids)


def production_key_problems(env: dict[str, str]) -> list[tuple[str, str]]:
    """Production failures for purpose keyrings. Reasons never include secret values."""
    from app.core.session import is_weak_secret

    problems: list[tuple[str, str]] = []
    seen_secret: dict[str, str] = {}
    for purpose, name in PURPOSE_ENV.items():
        raw = (env.get(name) or "").strip()
        if not raw:
            continue
        try:
            current, retired = _parse_keyring(raw, purpose)
        except KeyErrorSafe:
            problems.append((name, "is not a kid:secret list"))
            continue
        ids: list[str] = []
        for entry in (current, *retired):
            if entry.kid in ids:
                problems.append((name, "repeats a key id"))
            ids.append(entry.kid)
            if is_weak_secret(entry.secret):
                problems.append((name, "has a weak or placeholder key"))
            previous = seen_secret.get(entry.secret)
            if previous is not None:
                problems.append((name, f"reuses a key also configured for {previous}"))
            else:
                seen_secret[entry.secret] = name
    return problems
