"""MFA helpers (AUTH-211): TOTP secret encryption and verification."""

import base64
import hashlib

import pyotp
from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    """Fernet key derived from session secret (32 bytes for key)."""
    raw = hashlib.sha256(get_settings().session_secret.encode()).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt TOTP base32 secret for storage."""
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_totp_secret(encrypted: str) -> str:
    """Decrypt stored secret to base32."""
    return _fernet().decrypt(encrypted.encode()).decode()


def generate_totp_secret() -> str:
    """Generate a new base32 TOTP secret."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str, issuer: str = "Trust Copilot") -> str:
    """Provisioning URI for QR code."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify 6-digit TOTP code (current or adjacent window)."""
    if not code or len(code) != 6 or not code.isdigit():
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
