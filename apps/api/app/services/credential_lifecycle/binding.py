"""Workspace-bound AES-GCM for connector secrets.

TC-07-002 has not landed. ``KeyPurposePort.credential_ref`` is the AES-GCM
associated data. The seam names the purpose; it does not mint key bytes.
The AES key is HKDF-SHA256 of the session secret.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.services.provider_adapter.seams import KeyPurposePort, default_key_purpose

ENCRYPTION_VERSION = "tc20002:v1"
CIPHER_PREFIX = "tc20002:v1:"
DESTROYED = "destroyed"
_SALT = b"tc20002-connector-encryption"
_INFO_SUFFIX = "tc20002-v1"
_ENVELOPE_KEYS = ("access_key_id", "external_account_id", "region", "base_url")


class CredentialBindingError(Exception):
    """The ciphertext is unreadable for this workspace binding."""

    def __init__(self) -> None:
        super().__init__("credential cannot be decrypted")


@dataclass(frozen=True)
class Seal:
    ciphertext: str
    credential_ref: str
    last4: str | None
    fingerprint: str
    purpose_name: str
    encryption_version: str


def _aes_key(purpose_name: str) -> bytes:
    from app.core.session import get_session_secret

    info = f"{purpose_name}:{_INFO_SUFFIX}".encode()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=info,
    ).derive(get_session_secret().encode())


def _purpose(key_purpose: KeyPurposePort | None) -> KeyPurposePort:
    return key_purpose or default_key_purpose


def _last4(value: str) -> str | None:
    if len(value) < 4:
        return None
    return value[-4:]


def seal(
    value: str,
    *,
    workspace_id: int,
    source_type: str,
    credential_type: str,
    extra: dict | None = None,
    key_purpose: KeyPurposePort | None = None,
) -> Seal:
    """Encrypt ``value``. Associated data is the key-purpose credential ref."""
    purpose = _purpose(key_purpose)
    ref = purpose.credential_ref(
        workspace_id=workspace_id,
        source_type=source_type,
        credential_type=credential_type,
    )
    payload: dict[str, object] = {"v": 1, "secret": value}
    for key in _ENVELOPE_KEYS:
        item = (extra or {}).get(key)
        if isinstance(item, str) and item:
            payload[key] = item
    nonce = os.urandom(12)
    body = json.dumps(payload, separators=(",", ":")).encode()
    ciphertext = AESGCM(_aes_key(purpose.purpose_name)).encrypt(nonce, body, ref.encode())
    token = CIPHER_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode()
    return Seal(
        ciphertext=token,
        credential_ref=ref,
        last4=_last4(value),
        fingerprint=hashlib.sha256(value.encode()).hexdigest(),
        purpose_name=purpose.purpose_name,
        encryption_version=ENCRYPTION_VERSION,
    )


def open_envelope(
    token: str,
    *,
    workspace_id: int,
    source_type: str,
    credential_type: str,
    key_purpose: KeyPurposePort | None = None,
) -> dict:
    """Decrypt one envelope. A different workspace id fails closed."""
    if not token or token == DESTROYED or not token.startswith(CIPHER_PREFIX):
        raise CredentialBindingError()
    purpose = _purpose(key_purpose)
    ref = purpose.credential_ref(
        workspace_id=workspace_id,
        source_type=source_type,
        credential_type=credential_type,
    )
    raw = token[len(CIPHER_PREFIX) :]
    try:
        blob = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        plain = AESGCM(_aes_key(purpose.purpose_name)).decrypt(blob[:12], blob[12:], ref.encode())
        data = json.loads(plain.decode())
    except CredentialBindingError:
        raise
    except Exception:
        raise CredentialBindingError() from None
    if not isinstance(data, dict) or not isinstance(data.get("secret"), str):
        raise CredentialBindingError()
    return data
