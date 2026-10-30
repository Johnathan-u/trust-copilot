"""TC-07-002: purpose keyrings, legacy reads, rotation and MFA reset.

Synthetic keys and plaintext only. Every stored value contains a marker word.
"""

import base64
import hashlib
import json
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.core.keys import (
    KeyErrorSafe,
    current_session_key_id,
    open_sealed,
    production_key_problems,
    seal,
)
from app.core.key_rotation import rotate_keys
from app.core.mfa import decrypt_mfa_for_user, mfa_reenrol_required
from app.core.session import get_session_secret, sign_session, verify_token
from app.models.audit_event import AuditEvent
from app.models.credential_store import CredentialStore
from app.models.user import User
from app.models.user_mfa import UserMfa
from app.models.user_session import UserSession
from tests.release.conftest import OWNED, assert_back_to_baseline, counts, delete_owned

MFA_A = "synthetic-example-mfa-key-0123456789abcdef"
MFA_B = "synthetic-example-mfa-key-fedcba9876543210"
CONN_A = "synthetic-example-connector-key-0123456789"
SESS_A = "synthetic-example-session-key-0123456789ab"
SESS_B = "synthetic-example-session-key-ba9876543210fedc"
PLAIN_MFA = "synthetic example mfa totp secret"
PLAIN_CONN = "synthetic example connector token"


def _user(db: Session, tag: str) -> User:
    row = User(
        email=f"synthetic-example-rotation-{tag}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="synthetic-example-hash",
        display_name="synthetic example",
    )
    db.add(row)
    db.flush()
    OWNED["users"].append(row.id)
    return row


def _track_credentials(*rows: CredentialStore) -> None:
    OWNED["credentials"].extend(row.id for row in rows)


@pytest.fixture(autouse=True)
def _committed_rows_return_to_baseline(request):
    """Delete rows this module committed. db_session only rolls back its open transaction."""
    if "db_session" not in request.fixturenames:
        yield
        return
    db_session = request.getfixturevalue("db_session")
    for key in OWNED:
        OWNED[key].clear()
    before = counts(db_session)
    yield
    db_session.rollback()
    delete_owned(db_session)
    db_session.commit()
    assert_back_to_baseline(db_session, before)


def test_purpose_keys_do_not_decrypt_each_other(monkeypatch):
    monkeypatch.setenv("MFA_KEYRING", f"m1:{MFA_A}")
    monkeypatch.setenv("CONNECTOR_KEYRING", f"c1:{CONN_A}")
    sealed = seal("mfa", PLAIN_MFA)
    with pytest.raises(KeyErrorSafe):
        open_sealed("connector", sealed)
    assert open_sealed("mfa", sealed) == PLAIN_MFA


def test_legacy_unprefixed_ciphertext_still_opens(monkeypatch):
    monkeypatch.delenv("MFA_KEYRING", raising=False)
    raw = hashlib.sha256(get_session_secret().encode()).digest()
    token = Fernet(base64.urlsafe_b64encode(raw)).encrypt(PLAIN_MFA.encode()).decode()
    assert not token.startswith("v0-legacy.")
    assert open_sealed("mfa", token) == PLAIN_MFA


def test_rotation_reencrypts_under_the_new_key_id(db_session: Session, monkeypatch):
    monkeypatch.setenv("MFA_KEYRING", f"m1:{MFA_A}")
    user = _user(db_session, "rotate")
    db_session.add(
        UserMfa(user_id=user.id, totp_secret_encrypted=seal("mfa", PLAIN_MFA), enabled=True)
    )
    db_session.commit()
    monkeypatch.setenv("MFA_KEYRING", f"m2:{MFA_B},m1:{MFA_A}")
    first = rotate_keys(db_session, dry_run=True)
    assert first["mfa"]["reencrypted"] >= 1
    assert first["dry_run"] is True
    stored = (
        db_session.query(UserMfa).filter(UserMfa.user_id == user.id).one().totp_secret_encrypted
    )
    assert stored.startswith("m1.")
    rotate_keys(db_session, dry_run=False, commit=False)
    db_session.expire_all()
    stored = (
        db_session.query(UserMfa).filter(UserMfa.user_id == user.id).one().totp_secret_encrypted
    )
    assert stored.startswith("m2.")
    assert open_sealed("mfa", stored) == PLAIN_MFA
    third = rotate_keys(db_session, dry_run=False, commit=False)
    db_session.expire_all()
    again = db_session.query(UserMfa).filter(UserMfa.user_id == user.id).one().totp_secret_encrypted
    assert again.startswith("m2.")
    assert third["mfa"]["unchanged"] >= 1


def test_retired_session_key_is_rejected(monkeypatch):
    monkeypatch.setenv("SESSION_KEYRING", f"v1:{SESS_A}")
    token = sign_session(
        1,
        "synthetic-example@example.com",
        session_id="synthetic-example-sid",
        max_age_seconds=3600,
    )
    assert token.startswith("v1.")
    assert verify_token(token) is not None
    monkeypatch.setenv("SESSION_KEYRING", f"v2:{SESS_B},v1:{SESS_A}")
    assert verify_token(token) is None
    assert current_session_key_id() == "v2"


def test_wrong_key_fails_closed_without_leaking(monkeypatch, caplog):
    monkeypatch.setenv("CONNECTOR_KEYRING", f"c1:{CONN_A}")
    sealed = seal("connector", PLAIN_CONN)
    monkeypatch.setenv("CONNECTOR_KEYRING", f"c2:{MFA_B}")
    with pytest.raises(KeyErrorSafe) as caught:
        open_sealed("connector", sealed)
    message = str(caught.value)
    assert PLAIN_CONN not in message
    assert CONN_A not in message
    assert sealed not in message
    assert PLAIN_CONN not in caplog.text
    assert CONN_A not in caplog.text


def test_production_rejects_reused_and_weak_keys():
    weak = production_key_problems({"MFA_KEYRING": "v1:changeme"})
    assert any(name == "MFA_KEYRING" and "weak" in reason for name, reason in weak)
    reused = production_key_problems(
        {"MFA_KEYRING": f"m1:{MFA_A}", "CONNECTOR_KEYRING": f"c1:{MFA_A}"}
    )
    assert any("reuses a key" in reason for _, reason in reused)
    repeated = production_key_problems({"MFA_KEYRING": f"m1:{MFA_A},m1:{MFA_B}"})
    assert any("repeats a key id" in reason for _, reason in repeated)
    blob = repr(weak + reused + repeated)
    for secret in (MFA_A, MFA_B, "changeme"):
        assert secret not in blob


def test_rotation_resumes_from_after_id(db_session: Session, monkeypatch):
    monkeypatch.setenv("CONNECTOR_KEYRING", f"c1:{CONN_A}")
    first = CredentialStore(
        workspace_id=1,
        source_type="synthetic-example",
        credential_type=f"example-a-{uuid.uuid4().hex[:8]}",
        encrypted_value=seal("connector", PLAIN_CONN),
    )
    second = CredentialStore(
        workspace_id=1,
        source_type="synthetic-example",
        credential_type=f"example-b-{uuid.uuid4().hex[:8]}",
        encrypted_value=seal("connector", PLAIN_CONN + " b"),
    )
    db_session.add_all([first, second])
    db_session.commit()
    _track_credentials(first, second)
    ids = (first.id, second.id)
    monkeypatch.setenv("CONNECTOR_KEYRING", f"c2:{MFA_B},c1:{CONN_A}")
    rotate_keys(db_session, limit=1, after_id=ids[0] - 1, commit=False)
    db_session.expire_all()
    rows = (
        db_session.query(CredentialStore)
        .filter(CredentialStore.id.in_(ids))
        .order_by(CredentialStore.id.asc())
        .all()
    )
    assert rows[0].encrypted_value.startswith("c2.")
    assert rows[1].encrypted_value.startswith("c1.")
    rotate_keys(db_session, limit=1, after_id=rows[0].id, commit=False)
    db_session.expire_all()
    rows = (
        db_session.query(CredentialStore)
        .filter(CredentialStore.id.in_(ids))
        .order_by(CredentialStore.id.asc())
        .all()
    )
    assert rows[1].encrypted_value.startswith("c2.")
    assert open_sealed("connector", rows[1].encrypted_value) == PLAIN_CONN + " b"
    again = rotate_keys(db_session, after_id=ids[0] - 1, commit=False)
    assert again["credential_store"]["reencrypted"] == 0


def test_mfa_reenrol_when_secret_cannot_be_opened(db_session: Session, monkeypatch):
    monkeypatch.setenv("MFA_KEYRING", f"m2:{MFA_B}")
    user = _user(db_session, "reenrol")
    db_session.add(
        UserMfa(
            user_id=user.id,
            totp_secret_encrypted="gAAAA-synthetic-example-not-a-real-token",
            enabled=True,
        )
    )
    db_session.commit()
    report = rotate_keys(db_session, commit=False)
    assert report["mfa"]["reenrol"] >= 1
    db_session.expire_all()
    row = db_session.query(UserMfa).filter(UserMfa.user_id == user.id).one()
    assert row.enabled is True
    assert mfa_reenrol_required(row.totp_secret_encrypted)
    assert "synthetic example" not in row.totp_secret_encrypted
    audited = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == "crypto.decrypt_failed", AuditEvent.user_id == user.id)
        .all()
    )
    assert audited
    for event in audited:
        details = json.loads(event.details)
        assert set(details) == {"key_id", "reason"}
        assert details["reason"] == "decrypt_failed"
        assert "gAAAA" not in event.details
        assert event.email is None


def test_rotation_and_mfa_decrypt_failures_are_audited(db_session: Session, monkeypatch):
    monkeypatch.setenv("MFA_KEYRING", f"m2:{MFA_B}")
    monkeypatch.setenv("CONNECTOR_KEYRING", f"c2:{MFA_B}")
    user = _user(db_session, "audit")
    bad_mfa = "gAAAA-synthetic-example-not-a-real-token"
    bad_conn = "c1.synthetic-example-not-a-token"
    db_session.add(UserMfa(user_id=user.id, totp_secret_encrypted=bad_mfa, enabled=True))
    cred = CredentialStore(
        workspace_id=1,
        source_type="synthetic-example",
        credential_type=f"example-audit-{uuid.uuid4().hex[:8]}",
        encrypted_value=bad_conn,
    )
    db_session.add(cred)
    db_session.commit()
    _track_credentials(cred)
    rotate_keys(db_session, dry_run=True, commit=False)
    rotate_keys(db_session, dry_run=False, commit=False)
    mfa_events = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == "crypto.decrypt_failed", AuditEvent.user_id == user.id)
        .all()
    )
    assert len(mfa_events) == 2
    for event in mfa_events:
        assert json.loads(event.details) == {"key_id": "unknown", "reason": "decrypt_failed"}
        assert bad_mfa not in event.details
        assert MFA_B not in event.details
    conn_events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.action == "crypto.decrypt_failed",
            AuditEvent.resource_type == "credential_store",
            AuditEvent.resource_id == str(cred.id),
        )
        .all()
    )
    assert len(conn_events) == 2
    for event in conn_events:
        assert event.user_id is None
        assert json.loads(event.details) == {"key_id": "c1", "reason": "decrypt_failed"}
        assert bad_conn not in event.details
        assert MFA_B not in event.details


def test_mfa_helper_audits_a_failed_decrypt(db_session: Session, monkeypatch):
    monkeypatch.setenv("MFA_KEYRING", f"m2:{MFA_B}")
    user = _user(db_session, "helper")
    db_session.commit()
    bad_mfa = "m1.synthetic-example-not-a-token"
    with pytest.raises(KeyErrorSafe):
        decrypt_mfa_for_user(db_session, user_id=user.id, encrypted=bad_mfa, resource_id=user.id)
    direct = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.action == "crypto.decrypt_failed",
            AuditEvent.user_id == user.id,
            AuditEvent.resource_id == str(user.id),
        )
        .one()
    )
    assert json.loads(direct.details) == {"key_id": "m1", "reason": "decrypt_failed"}
    assert bad_mfa not in direct.details
    assert MFA_A not in direct.details
    assert MFA_B not in direct.details


def test_retired_session_rows_are_revoked(db_session: Session, monkeypatch):
    monkeypatch.setenv("SESSION_KEYRING", f"v2:{SESS_B},v1:{SESS_A}")
    user = _user(db_session, "sess")
    session_id = f"synthetic-example-session-{uuid.uuid4().hex[:12]}"
    db_session.add(
        UserSession(
            user_id=user.id,
            session_id=session_id,
            signing_key_id="v1",
        )
    )
    db_session.commit()
    report = rotate_keys(db_session, commit=False)
    assert report["sessions_revoked"] >= 1
    left = db_session.query(UserSession).filter(UserSession.session_id == session_id).one_or_none()
    assert left is None


def test_prefixed_mfa_ciphertext_fits_the_column(monkeypatch):
    monkeypatch.setenv("MFA_KEYRING", "k" * 32 + ":" + MFA_A)
    # kid is invalid if it is 32 k's? _KID_RE allows 32 chars starting with alnum. "k"*32 is ok.
    plain = "synthetic-" + ("e" * 180)
    sealed = seal("mfa", plain)
    assert sealed.startswith("k" * 32 + ".")
    assert len(sealed) <= 512
    assert open_sealed("mfa", sealed) == plain
