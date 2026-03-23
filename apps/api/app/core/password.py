"""Password hashing (AUTH-04). Argon2id default; no truncation, no composition gimmicks."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher(time_cost=2, memory_cost=65536)


def hash_password(plain: str) -> str:
    """Hash password with Argon2id. Do not truncate; pass through as-is."""
    return _hasher.hash(plain)


def verify_password(plain: str, hash_str: str) -> bool:
    """Verify plain password against stored hash. Returns True if match."""
    try:
        _hasher.verify(hash_str, plain)
        return True
    except (VerifyMismatchError, Exception):
        return False
