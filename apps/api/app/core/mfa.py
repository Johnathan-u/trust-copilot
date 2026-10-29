"""MFA helpers (AUTH-211): TOTP secret encryption and verification."""

import pyotp

from app.core.keys import MfaReenrolRequired, open_sealed, seal


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt TOTP base32 secret for storage."""
    return seal("mfa", secret)


def decrypt_totp_secret(encrypted: str) -> str:
    """Decrypt stored secret to base32."""
    return open_sealed("mfa", encrypted)


def mfa_reenrol_required(encrypted: str | None) -> bool:
    """True when rotation could not open the stored MFA secret."""
    if not encrypted:
        return False
    if encrypted.startswith("reenrol."):
        return True
    try:
        decrypt_totp_secret(encrypted)
    except MfaReenrolRequired:
        return True
    except Exception:
        return False
    return False


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
