"""Credential store service — encrypted storage with rotation tracking."""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.keys import open_sealed, seal
from app.models.credential_store import CredentialStore

logger = logging.getLogger(__name__)


def encrypt(value: str) -> str:
    return seal("connector", value)


def decrypt(encrypted: str) -> str:
    return open_sealed("connector", encrypted)


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
) -> dict:
    """Store or update an encrypted credential."""
    existing = (
        db.query(CredentialStore)
        .filter(
            CredentialStore.workspace_id == workspace_id,
            CredentialStore.source_type == source_type,
            CredentialStore.credential_type == credential_type,
        )
        .first()
    )

    encrypted_value = encrypt(value)
    now = datetime.now(timezone.utc)

    if existing:
        existing.encrypted_value = encrypted_value
        existing.last_rotated_at = now
        existing.status = "active"
        if rotation_interval_days is not None:
            existing.rotation_interval_days = rotation_interval_days
        if expires_at is not None:
            existing.expires_at = expires_at
        if metadata is not None:
            existing.metadata_json = json.dumps(metadata)
        db.flush()
        return _serialize(existing, include_value=False)

    cred = CredentialStore(
        workspace_id=workspace_id,
        source_type=source_type,
        credential_type=credential_type,
        encrypted_value=encrypted_value,
        rotation_interval_days=rotation_interval_days,
        expires_at=expires_at,
        last_rotated_at=now,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(cred)
    db.flush()
    return _serialize(cred, include_value=False)


def get_credential(
    db: Session, workspace_id: int, source_type: str, credential_type: str
) -> str | None:
    """Retrieve and decrypt a credential value. Returns None if not found."""
    row = (
        db.query(CredentialStore)
        .filter(
            CredentialStore.workspace_id == workspace_id,
            CredentialStore.source_type == source_type,
            CredentialStore.credential_type == credential_type,
            CredentialStore.status == "active",
        )
        .first()
    )
    if not row:
        return None
    return decrypt(row.encrypted_value)


def list_credentials(db: Session, workspace_id: int) -> list[dict]:
    """List all credentials for a workspace (without values)."""
    rows = db.query(CredentialStore).filter(CredentialStore.workspace_id == workspace_id).all()
    return [_serialize(r, include_value=False) for r in rows]


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
        .first()
    )
    if not row:
        return False
    row.status = "revoked"
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
    for r in rows:
        if r.last_rotated_at and r.rotation_interval_days:
            next_rotation = r.last_rotated_at + timedelta(days=r.rotation_interval_days)
            if now >= next_rotation:
                due.append(_serialize(r, include_value=False))
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
    return [_serialize(r, include_value=False) for r in rows]


def _serialize(row: CredentialStore, include_value: bool = False) -> dict:
    d = {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "source_type": row.source_type,
        "credential_type": row.credential_type,
        "status": row.status,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_rotated_at": row.last_rotated_at.isoformat() if row.last_rotated_at else None,
        "rotation_interval_days": row.rotation_interval_days,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_value:
        d["value"] = decrypt(row.encrypted_value)
    return d
