"""Human-readable invite verification codes (AUTH-208)."""

import hashlib
import secrets

# Unambiguous alphabet (no 0/O, 1/I/L confusion).
_INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 12


def normalize_invite_code(code: str) -> str:
    """Uppercase alphanumeric only (strips spaces, hyphens, etc.)."""
    return "".join(c for c in (code or "").upper() if c.isalnum())


def hash_invite_code(code: str) -> str:
    """SHA-256 hex of normalized code."""
    return hashlib.sha256(normalize_invite_code(code).encode()).hexdigest()


def generate_invite_code_pair() -> tuple[str, str]:
    """Return (formatted_for_email, normalized) e.g. ('AB12-CD34-EF56', 'AB12CD34EF56')."""
    raw = "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    formatted = f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"
    return formatted, raw
