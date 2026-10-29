"""MFA helpers (AUTH-211): TOTP secret encryption and verification."""

import pyotp
from sqlalchemy.orm import Session

from app.core.keys import REENROL_MARK, KeyErrorSafe, MfaReenrolRequired, open_sealed, seal


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt TOTP base32 secret for storage."""
    return seal("mfa", secret)


def decrypt_totp_secret(encrypted: str) -> str:
    """Decrypt stored secret to base32."""
    return open_sealed("mfa", encrypted)


def mfa_reenrol_required(encrypted: str | None) -> bool:
    """True when the stored MFA secret is the undecryptable ``reenrol.<kid>`` marker."""
    return bool(encrypted) and encrypted.startswith(f"{REENROL_MARK}.")


def decrypt_mfa_for_user(
    db: Session,
    *,
    user_id: int,
    encrypted: str,
    resource_id: int | None = None,
) -> str:
    """Open an MFA secret. A failure is audited with user id, key id and reason only."""
    try:
        return decrypt_totp_secret(encrypted)
    except (KeyErrorSafe, MfaReenrolRequired) as exc:
        from app.core.audit import record_decrypt_failure

        reason = "reenrol_marker" if isinstance(exc, MfaReenrolRequired) else "decrypt_failed"
        record_decrypt_failure(
            db,
            user_id=user_id,
            stored=encrypted,
            reason=reason,
            resource_type="user_mfa",
            resource_id=resource_id,
            commit=True,
        )
        raise


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
