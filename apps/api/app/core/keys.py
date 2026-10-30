"""Versioned key custody for session, OAuth-state, MFA and connector secrets.

Each purpose has its own keyring. When the purpose env var is unset, the
current key id is ``v0-legacy`` and the key is HKDF(SESSION_SECRET, purpose).
Unprefixed ciphertext and signatures use the retained v0-legacy entry's old
SHA256 or raw HMAC derivation. Explicit keyrings do not implicitly trust
SESSION_SECRET, and signatures always obey the caller's retirement policy.

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
# The punctuation prevents collision with a configured key id.
REENROL_PENDING_MARK = "reenrol-pending!"


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


def _material(entry: KeyEntry, purpose: str) -> bytes:
    # A prefixed key id has the same derivation before and after configuration.
    return _hkdf(entry.secret, purpose, entry.kid)


def _read_materials(entry: KeyEntry, purpose: str, env: dict[str, str] | None) -> tuple[bytes, ...]:
    material = _material(entry, purpose)
    source = os.environ if env is None else env
    if entry.kid == LEGACY_KID and (source.get(PURPOSE_ENV[purpose]) or "").strip():
        # Earlier explicit v0-legacy writers used SHA256. Only the explicitly
        # retained entry for this purpose may supply that compatibility key.
        return material, _legacy_sha256(entry.secret)
    return (material,)


def _fernet(material: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(material))


def seal(purpose: str, plaintext: str, env: dict[str, str] | None = None) -> str:
    ring = keyring_for(purpose, env)
    material = _material(ring.current, purpose)
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
    if stored.startswith(f"{REENROL_PENDING_MARK}."):
        stored = stored.split(".", 1)[1]
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
    if purpose == "mfa" and stored.startswith(f"{REENROL_PENDING_MARK}."):
        stored = stored.split(".", 1)[1]
    if stored.startswith(f"{REENROL_MARK}."):
        raise MfaReenrolRequired("mfa secret must be enrolled again")
    ring = keyring_for(purpose, env)
    try:
        if stored.startswith(_FERNET_PREFIX):
            legacy = ring.find(LEGACY_KID)
            if legacy is None:
                raise KeyErrorSafe("legacy key is not retained")
            return _fernet(_legacy_sha256(legacy.secret)).decrypt(stored.encode()).decode()
        kid, token = stored.split(".", 1)
        entry = ring.find(kid)
        if entry is None:
            raise KeyErrorSafe("unknown key id")
        for material in _read_materials(entry, purpose, env):
            try:
                return _fernet(material).decrypt(token.encode()).decode()
            except InvalidToken:
                continue
        raise KeyErrorSafe("ciphertext could not be opened")
    except MfaReenrolRequired:
        raise
    except (InvalidToken, KeyErrorSafe, ValueError):
        raise KeyErrorSafe("ciphertext could not be opened") from None


def sign_with_purpose(purpose: str, data: str, env: dict[str, str] | None = None) -> str:
    ring = keyring_for(purpose, env)
    material = _material(ring.current, purpose)
    sig = hmac.new(material, data.encode(), "sha256").hexdigest()
    return f"{ring.current.kid}.{data}.{sig}"


def verify_with_purpose(
    purpose: str, token: str, *, accept_retired: bool, env: dict[str, str] | None = None
) -> str | None:
    """Return a verified payload only when its key is allowed by the caller.

    Unprefixed tokens belong to v0-legacy and use that entry's raw HMAC key.
    An explicit keyring never implicitly trusts SESSION_SECRET as another key.
    """
    if not token or token.count(".") not in (1, 2):
        return None
    ring = keyring_for(purpose, env)
    try:
        if token.count(".") == 1:
            data, sig = token.split(".", 1)
            legacy = ring.find(LEGACY_KID)
            if legacy is None or (ring.current.kid != LEGACY_KID and not accept_retired):
                return None
            expected = hmac.new(legacy.secret.encode(), data.encode(), "sha256").hexdigest()
            if hmac.compare_digest(sig, expected):
                return data
            return None
        kid, data, sig = token.split(".", 2)
        entry = ring.find(kid)
        if entry is None or (kid != ring.current.kid and not accept_retired):
            return None
        for material in _read_materials(entry, purpose, env):
            expected = hmac.new(material, data.encode(), "sha256").hexdigest()
            if hmac.compare_digest(sig, expected):
                return data
        return None
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
