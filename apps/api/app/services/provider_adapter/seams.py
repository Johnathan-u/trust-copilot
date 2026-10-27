"""Narrow stand-ins for prerequisite contracts that are not on master yet.

TC-07-002 (key purposes), TC-10-003 (idempotent side effects) and TC-08-001
(immutable document versions) are consumed only through these protocols.
Each default is local and intentionally incomplete. Swap the default when the
prerequisite lands; callers should accept the protocol, not the concrete class.
"""

from __future__ import annotations

import hashlib
from typing import Protocol


class KeyPurposePort(Protocol):
    """TC-07-002 seam. Names a key purpose. Does not generate or rotate keys."""

    purpose_name: str

    def credential_ref(
        self,
        *,
        workspace_id: int | None,
        source_type: str,
        credential_type: str,
    ) -> str:
        """Non-secret reference. Never the credential material."""


class LocalKeyPurpose:
    """Names connector encryption only. Not versioned custody or rotation."""

    purpose_name = "connector_encryption"

    def credential_ref(
        self,
        *,
        workspace_id: int | None,
        source_type: str,
        credential_type: str,
    ) -> str:
        workspace = workspace_id if workspace_id is not None else "none"
        return f"key-purpose:{self.purpose_name}:v0:ws:{workspace}:{source_type}:{credential_type}"


class SideEffectIdempotencyPort(Protocol):
    """TC-10-003 seam. Claims one key. Does not lease jobs or survive crashes."""

    def claim(self, key: str) -> bool:
        """Return True when this caller should apply the side effect."""


class MemorySideEffectIdempotency:
    """Process-local claim set. A restart forgets every key."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()

    def claim(self, key: str) -> bool:
        if not key or key in self._claimed:
            return False
        self._claimed.add(key)
        return True


class SourceVersionPort(Protocol):
    """TC-08-001 seam. Returns a token. Does not hash document bytes or locators."""

    def source_version(
        self,
        *,
        workspace_id: int | None,
        provider: str,
        resource_id: str,
        object_revision: str,
    ) -> str:
        """Content-free source version token for one observation."""


class LocalSourceVersion:
    """Stable token of provider identity, not an immutable document hash."""

    def source_version(
        self,
        *,
        workspace_id: int | None,
        provider: str,
        resource_id: str,
        object_revision: str,
    ) -> str:
        material = f"{workspace_id}|{provider}|{resource_id}|{object_revision}".encode()
        digest = hashlib.sha256(material).hexdigest()[:16]
        return f"srcver:v0-local:{digest}"


default_key_purpose = LocalKeyPurpose()
default_idempotency = MemorySideEffectIdempotency()
default_source_version = LocalSourceVersion()
