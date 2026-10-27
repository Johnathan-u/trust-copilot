"""Credential store service — encrypted storage with rotation tracking.

Ciphertext is workspace-bound AES-GCM (TC-20-002). Fernet rows written before
that change are rewrapped only when the owning workspace reads them.
``decrypt`` does not accept Fernet, so a guessed workspace id cannot open it.
"""

import json
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.models.credential_store import CredentialStore
from app.services.credential_lifecycle.binding import (
    CIPHER_PREFIX,
    DESTROYED,
    CredentialBindingError,
    open_envelope,
    seal,
)
from app.services.provider_adapter.contract import ObservationState, ProvenanceKind
from app.services.provider_adapter.surfaces import action_contract


def _get_fernet() -> Fernet:
    """Legacy Fernet key. New writes use ``seal``."""
    import base64
    import hashlib

    from app.core.session import get_session_secret

    secret = get_session_secret()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()[:32])
    return Fernet(key)


def _legacy_plaintext(token: str) -> str | None:
    if not token or token.startswith(CIPHER_PREFIX) or token == DESTROYED:
        return None
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except Exception:
        return None


def encrypt(
    value: str,
    *,
    workspace_id: int,
    source_type: str,
    credential_type: str,
    extra: dict | None = None,
) -> str:
    return seal(
        value,
        workspace_id=workspace_id,
        source_type=source_type,
        credential_type=credential_type,
        extra=extra,
    ).ciphertext


def decrypt(
    encrypted: str,
    *,
    workspace_id: int,
    source_type: str,
    credential_type: str,
) -> str:
    """Open an AES-GCM envelope. Fernet and a mismatched workspace both fail."""
    return open_envelope(
        encrypted,
        workspace_id=workspace_id,
        source_type=source_type,
        credential_type=credential_type,
    )["secret"]


def _public_account(account: object, value: str) -> str | None:
    if not isinstance(account, str) or not account or account == value:
        return None
    if len(account) >= 8 and account in value:
        return None
    return account[:255]


def _apply_seal(
    row: CredentialStore,
    value: str,
    *,
    extra: dict | None = None,
) -> None:
    sealed = seal(
        value,
        workspace_id=row.workspace_id,
        source_type=row.source_type,
        credential_type=row.credential_type,
        extra=extra,
    )
    row.encrypted_value = sealed.ciphertext
    row.secret_last4 = sealed.last4
    row.secret_fingerprint = sealed.fingerprint
    row.credential_ref = sealed.credential_ref
    row.key_purpose = sealed.purpose_name
    row.encryption_version = sealed.encryption_version
    row.external_account_id = _public_account((extra or {}).get("external_account_id"), value)
    row.destroyed_at = None
    row.status = "active"


def _destroy(row: CredentialStore) -> None:
    row.encrypted_value = DESTROYED
    row.status = "revoked"
    row.destroyed_at = datetime.now(timezone.utc)
    row.secret_last4 = None
    row.secret_fingerprint = None


def store_credential(
    db: Session,
    workspace_id: int,
    source_type: str,
    credential_type: str,
    value: str,
    *,
    rotation_interval_days: int | None = None,
    expires_at: datetime | None = None,
    metadata: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Store or update an encrypted credential. Does not call the provider."""
    existing = (
        db.query(CredentialStore)
        .filter(
            CredentialStore.workspace_id == workspace_id,
            CredentialStore.source_type == source_type,
            CredentialStore.credential_type == credential_type,
        )
        .order_by(CredentialStore.id.asc())
        .first()
    )
    now = datetime.now(timezone.utc)

    if existing:
        _apply_seal(existing, value, extra=extra)
        existing.last_rotated_at = now
        if rotation_interval_days is not None:
            existing.rotation_interval_days = rotation_interval_days
        if expires_at is not None:
            existing.expires_at = expires_at
        if metadata is not None:
            existing.metadata_json = json.dumps(metadata)
        db.flush()
        return _serialize(existing)

    cred = CredentialStore(
        workspace_id=workspace_id,
        source_type=source_type,
        credential_type=credential_type,
        encrypted_value=DESTROYED,
        rotation_interval_days=rotation_interval_days,
        expires_at=expires_at,
        last_rotated_at=now,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    _apply_seal(cred, value, extra=extra)
    db.add(cred)
    db.flush()
    return _serialize(cred)


def read_material(db: Session, row: CredentialStore) -> dict | None:
    """Return the envelope for an active row, rewrapping legacy Fernet once."""
    if row.status != "active" or not row.encrypted_value or row.encrypted_value == DESTROYED:
        return None
    try:
        return open_envelope(
            row.encrypted_value,
            workspace_id=row.workspace_id,
            source_type=row.source_type,
            credential_type=row.credential_type,
        )
    except CredentialBindingError:
        plain = _legacy_plaintext(row.encrypted_value)
        if plain is None:
            return None
        _apply_seal(row, plain)
        db.flush()
        return {"v": 1, "secret": plain}


def get_credential(
    db: Session, workspace_id: int, source_type: str, credential_type: str
) -> str | None:
    """Return the secret string, or None when the row is missing or destroyed."""
    row = (
        db.query(CredentialStore)
        .filter(
            CredentialStore.workspace_id == workspace_id,
            CredentialStore.source_type == source_type,
            CredentialStore.credential_type == credential_type,
            CredentialStore.status == "active",
        )
        .order_by(CredentialStore.id.asc())
        .first()
    )
    if not row:
        return None
    material = read_material(db, row)
    if not material:
        return None
    secret = material.get("secret")
    return secret if isinstance(secret, str) else None


def list_credentials(db: Session, workspace_id: int) -> list[dict]:
    """List credentials for one workspace. Secret material is never included."""
    rows = db.query(CredentialStore).filter(CredentialStore.workspace_id == workspace_id).all()
    return [_serialize(r) for r in rows]


def list_observation_contract(workspace_id: int) -> dict:
    """Listing credential refs is custody metadata, not collected evidence."""
    return action_contract(
        provider="credential_store",
        resource_id="credential:list",
        state=ObservationState.UNKNOWN,
        provenance_kind=ProvenanceKind.CREDENTIAL_CUSTODY,
        workspace_id=workspace_id,
        error_code="not_evidence",
        safe_message="Credential inventory is not collected evidence",
        note="list",
    )


def revoke_credential(
    db: Session, workspace_id: int, source_type: str, credential_type: str
) -> bool:
    row = (
        db.query(CredentialStore)
        .filter(
            CredentialStore.workspace_id == workspace_id,
            CredentialStore.source_type == source_type,
            CredentialStore.credential_type == credential_type,
        )
        .order_by(CredentialStore.id.asc())
        .first()
    )
    if not row:
        return False
    _destroy(row)
    db.flush()
    return True


def check_rotation_due(db: Session, workspace_id: int) -> list[dict]:
    """Find credentials that need rotation."""
    rows = (
        db.query(CredentialStore)
        .filter(
            CredentialStore.workspace_id == workspace_id,
            CredentialStore.status == "active",
            CredentialStore.rotation_interval_days.isnot(None),
        )
        .all()
    )
    due = []
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.last_rotated_at and row.rotation_interval_days:
            next_rotation = row.last_rotated_at + timedelta(days=row.rotation_interval_days)
            if now >= next_rotation:
                due.append(_serialize(row))
    return due


def check_expiring(db: Session, workspace_id: int, days_ahead: int = 7) -> list[dict]:
    """Find credentials expiring within the given window."""
    cutoff = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    rows = (
        db.query(CredentialStore)
        .filter(
            CredentialStore.workspace_id == workspace_id,
            CredentialStore.status == "active",
            CredentialStore.expires_at.isnot(None),
            CredentialStore.expires_at <= cutoff,
        )
        .all()
    )
    return [_serialize(r) for r in rows]


def _serialize(row: CredentialStore, include_value: bool = False) -> dict:
    del include_value  # secret material is never serialized
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "source_type": row.source_type,
        "credential_type": row.credential_type,
        "status": row.status,
        "secret_last4": row.secret_last4,
        "secret_fingerprint": row.secret_fingerprint,
        "key_purpose": row.key_purpose,
        "credential_ref": row.credential_ref,
        "encryption_version": row.encryption_version,
        "external_account_id": row.external_account_id,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_rotated_at": row.last_rotated_at.isoformat() if row.last_rotated_at else None,
        "rotation_interval_days": row.rotation_interval_days,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "destroyed_at": row.destroyed_at.isoformat() if row.destroyed_at else None,
        "observation_contract": action_contract(
            provider=row.source_type,
            resource_id=f"credential:{row.source_type}:{row.credential_type}",
            state=ObservationState.UNKNOWN,
            provenance_kind=ProvenanceKind.CREDENTIAL_CUSTODY,
            workspace_id=row.workspace_id,
            credential_type=row.credential_type,
            error_code="not_evidence",
            safe_message="Credential custody is not collected evidence",
            note="Secret material is not part of this observation",
        ),
    }
