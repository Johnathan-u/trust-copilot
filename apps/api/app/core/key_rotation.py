"""Re-encrypt purpose ciphertexts and revoke sessions for retired session keys.

Reports counts only. Plaintext and ciphertext are never logged. Refuses to run
when APP_ENV is production so this rehearsal command is not pointed at live data.
"""

from __future__ import annotations

import os
from typing import Callable

from sqlalchemy.orm import Session

from app.core.keys import (
    LEGACY_KID,
    MfaReenrolRequired,
    REENROL_MARK,
    REENROL_PENDING_MARK,
    KeyErrorSafe,
    keyring_for,
    open_sealed,
    seal,
)
from app.models.credential_store import CredentialStore
from app.models.gmail_integration import GmailIntegration
from app.models.slack_integration import SlackIntegration
from app.models.user_mfa import UserMfa
from app.models.user_session import UserSession


def _refuse_production() -> None:
    from app.core.session import is_production_env

    if is_production_env():
        raise SystemExit(
            "Refusing key rotation when APP_ENV=production. "
            "Run it on a copy. This command does not accept a production override."
        )


def _already_current(stored: str, purpose: str) -> bool:
    if purpose == "mfa" and stored.startswith(f"{REENROL_PENDING_MARK}."):
        stored = stored.split(".", 1)[1]
    kid = keyring_for(purpose).current.kid
    return stored.startswith(f"{kid}.")


def _row_user_id(row: object) -> int | None:
    value = getattr(row, "user_id", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _rotate_column(
    db: Session,
    rows: list,
    purpose: str,
    read: Callable,
    write: Callable,
    *,
    dry_run: bool,
    on_fail: Callable | None,
) -> dict[str, int]:
    from app.core.audit import record_decrypt_failure

    counts = {"reencrypted": 0, "unchanged": 0, "failed": 0, "reenrol": 0}
    for row in rows:
        stored = read(row)
        if stored is None:
            counts["unchanged"] += 1
            continue
        if isinstance(stored, str) and stored.startswith(f"{REENROL_MARK}."):
            counts["unchanged"] += 1
            continue
        if isinstance(stored, str) and _already_current(stored, purpose):
            counts["unchanged"] += 1
            continue
        try:
            plain = open_sealed(purpose, stored)
        except (KeyErrorSafe, MfaReenrolRequired) as exc:
            reason = "reenrol_marker" if isinstance(exc, MfaReenrolRequired) else "decrypt_failed"
            record_decrypt_failure(
                db,
                user_id=_row_user_id(row),
                stored=stored if isinstance(stored, str) else None,
                reason=reason,
                resource_type=getattr(row, "__tablename__", purpose),
                resource_id=getattr(row, "id", None),
                commit=False,
            )
            if on_fail is not None:
                if not dry_run:
                    on_fail(row)
                counts["reenrol"] += 1
            else:
                counts["failed"] += 1
            continue
        if not dry_run:
            replacement = seal(purpose, plain)
            if purpose == "mfa" and stored.startswith(f"{REENROL_PENDING_MARK}."):
                replacement = f"{REENROL_PENDING_MARK}.{replacement}"
            write(row, replacement)
        counts["reencrypted"] += 1
    return counts


def _revoke_retired_sessions(db: Session, *, dry_run: bool) -> int:
    ring = keyring_for("session")
    retired = {entry.kid for entry in ring.retired}
    if ring.current.kid != LEGACY_KID:
        retired.add(LEGACY_KID)
    cond = None
    if retired:
        cond = UserSession.signing_key_id.in_(sorted(retired))
    if ring.current.kid != LEGACY_KID:
        nulls = UserSession.signing_key_id.is_(None)
        cond = nulls if cond is None else (cond | nulls)
    if cond is None:
        return 0
    query = db.query(UserSession).filter(cond)
    count = query.count()
    if not dry_run and count:
        query.delete(synchronize_session=False)
    return count


def rotate_keys(
    db: Session,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    after_id: int = 0,
    commit: bool = True,
) -> dict:
    """Re-encrypt rows still on an older key id. Safe to repeat."""
    _refuse_production()

    def take(model, id_attr):
        q = db.query(model).filter(id_attr > after_id).order_by(id_attr.asc())
        if limit is not None:
            q = q.limit(limit)
        return q.all()

    def mark_reenrol(row: UserMfa) -> None:
        row.totp_secret_encrypted = f"{REENROL_MARK}.{keyring_for('mfa').current.kid}"
        row.enabled = True

    mfa = _rotate_column(
        db,
        take(UserMfa, UserMfa.id),
        "mfa",
        lambda row: row.totp_secret_encrypted,
        lambda row, value: setattr(row, "totp_secret_encrypted", value),
        dry_run=dry_run,
        on_fail=mark_reenrol,
    )
    connectors = _rotate_column(
        db,
        take(CredentialStore, CredentialStore.id),
        "connector",
        lambda row: row.encrypted_value,
        lambda row, value: setattr(row, "encrypted_value", value),
        dry_run=dry_run,
        on_fail=None,
    )
    slack = _rotate_column(
        db,
        take(SlackIntegration, SlackIntegration.id),
        "connector",
        lambda row: row.bot_token_encrypted,
        lambda row, value: setattr(row, "bot_token_encrypted", value),
        dry_run=dry_run,
        on_fail=None,
    )
    gmail_rows = take(GmailIntegration, GmailIntegration.id)
    gmail_access = _rotate_column(
        db,
        gmail_rows,
        "connector",
        lambda row: row.access_token_encrypted,
        lambda row, value: setattr(row, "access_token_encrypted", value),
        dry_run=dry_run,
        on_fail=None,
    )
    gmail_refresh = _rotate_column(
        db,
        gmail_rows,
        "connector",
        lambda row: row.refresh_token_encrypted,
        lambda row, value: setattr(row, "refresh_token_encrypted", value),
        dry_run=dry_run,
        on_fail=None,
    )
    revoked = _revoke_retired_sessions(db, dry_run=dry_run)
    if not dry_run:
        db.flush()
    if commit and not dry_run:
        db.commit()
    return {
        "dry_run": dry_run,
        "after_id": after_id,
        "limit": limit,
        "mfa": mfa,
        "credential_store": connectors,
        "slack": slack,
        "gmail_access": gmail_access,
        "gmail_refresh": gmail_refresh,
        "sessions_revoked": revoked,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Re-encrypt purpose keys. Prints counts only.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--after-id", type=int, default=0)
    args = parser.parse_args(argv)
    if os.environ.get("APP_ENV", "").strip().lower() == "production":
        print("refusing key rotation when APP_ENV=production", flush=True)
        return 2
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        report = rotate_keys(db, dry_run=args.dry_run, limit=args.limit, after_id=args.after_id)
    finally:
        db.close()
    print(json.dumps(report), flush=True)
    return 0
