"""TC-07-002: an undecryptable MFA secret needs an administrator reset.

Synthetic users and passwords only. Login in the reenrol state issues no session.
"""

import json
import uuid

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models.audit_event import AuditEvent
from app.models.user import User, WorkspaceMember
from app.models.user_mfa import UserMfa
from app.models.user_session import UserSession
from app.models.workspace import Workspace

LOGIN_PHRASE = "synthetic-example-mfa-reset-password"
REENROL = "reenrol.m2"


def _user(db: Session, tag: str) -> User:
    row = User(
        email=f"synthetic-example-mfa-{tag}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(LOGIN_PHRASE),
        display_name="synthetic example",
        email_verified=True,
    )
    db.add(row)
    db.flush()
    return row


def _workspace(db: Session, tag: str) -> Workspace:
    db.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM workspaces))"
        )
    )
    row = Workspace(
        name=f"synthetic example {tag}",
        slug=f"synthetic-example-{tag}-{uuid.uuid4().hex[:10]}",
        mfa_required=True,
    )
    db.add(row)
    db.flush()
    return row


def _member(db: Session, workspace: Workspace, user: User, role: str) -> None:
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role))
    db.flush()


def _reenrol(db: Session, user: User) -> UserMfa:
    row = UserMfa(user_id=user.id, totp_secret_encrypted=REENROL, enabled=True)
    db.add(row)
    db.flush()
    return row


def test_reenrol_login_issues_no_session_and_admin_reset_restores_enrolment(
    client: TestClient, db_session: Session
):
    workspace = _workspace(db_session, "home")
    user = _user(db_session, "locked")
    admin = _user(db_session, "admin")
    _member(db_session, workspace, user, "editor")
    _member(db_session, workspace, admin, "admin")
    _reenrol(db_session, user)
    db_session.commit()

    denied = client.post("/api/auth/login", json={"email": user.email, "password": LOGIN_PHRASE})
    assert denied.status_code == 403
    body = denied.json()
    assert body["error"]["code"] == "mfa_reset_required"
    assert REENROL not in denied.text
    assert denied.headers.get("set-cookie") is None
    assert "tc_session" not in denied.cookies
    db_session.expire_all()
    assert db_session.query(UserSession).filter(UserSession.user_id == user.id).count() == 0
    setup = client.post("/api/auth/mfa/setup")
    assert setup.status_code == 401

    logged_admin = client.post(
        "/api/auth/login", json={"email": admin.email, "password": LOGIN_PHRASE}
    )
    assert logged_admin.status_code == 200
    cleared = client.post(f"/api/members/clear-mfa-reenrol/{user.id}")
    assert cleared.status_code == 200
    assert cleared.json()["mfa_required"] is True
    db_session.expire_all()
    row = db_session.query(UserMfa).filter(UserMfa.user_id == user.id).one()
    assert row.enabled is False
    assert not row.totp_secret_encrypted.startswith("reenrol.")
    home = db_session.query(Workspace).filter(Workspace.id == workspace.id).one()
    assert home.mfa_required is True
    audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.action == "auth.mfa_reenrol_cleared",
            AuditEvent.user_id == admin.id,
            AuditEvent.workspace_id == workspace.id,
        )
        .one()
    )
    details = json.loads(audit.details)
    assert details["target_user_id"] == user.id
    assert details["mfa_required"] is True
    assert REENROL not in audit.details

    logged_user = client.post(
        "/api/auth/login", json={"email": user.email, "password": LOGIN_PHRASE}
    )
    assert logged_user.status_code == 200
    assert logged_user.headers.get("set-cookie")
    started = client.post("/api/auth/mfa/setup")
    assert started.status_code == 200
    secret = started.json()["secret"]
    confirmed = client.post("/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert confirmed.status_code == 200
    db_session.expire_all()
    enrolled = db_session.query(UserMfa).filter(UserMfa.user_id == user.id).one()
    assert enrolled.enabled is True
    assert not enrolled.totp_secret_encrypted.startswith("reenrol.")

    login_audit = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == "crypto.decrypt_failed", AuditEvent.user_id == user.id)
        .one()
    )
    assert json.loads(login_audit.details) == {"key_id": "m2", "reason": "reenrol_marker"}
    assert REENROL not in login_audit.details


def test_reenrol_reset_denies_non_admin_and_cross_workspace_admin(
    client: TestClient, db_session: Session
):
    home = _workspace(db_session, "home")
    other = _workspace(db_session, "other")
    user = _user(db_session, "target")
    editor = _user(db_session, "editor")
    outsider = _user(db_session, "outsider")
    _member(db_session, home, user, "editor")
    _member(db_session, home, editor, "editor")
    _member(db_session, other, outsider, "admin")
    _reenrol(db_session, user)
    db_session.commit()

    logged_editor = client.post(
        "/api/auth/login", json={"email": editor.email, "password": LOGIN_PHRASE}
    )
    assert logged_editor.status_code == 200
    rejected = client.post(f"/api/members/clear-mfa-reenrol/{user.id}")
    assert rejected.status_code == 403

    logged_outsider = client.post(
        "/api/auth/login", json={"email": outsider.email, "password": LOGIN_PHRASE}
    )
    assert logged_outsider.status_code == 200
    missing = client.post(f"/api/members/clear-mfa-reenrol/{user.id}")
    assert missing.status_code == 404

    db_session.expire_all()
    row = db_session.query(UserMfa).filter(UserMfa.user_id == user.id).one()
    assert row.totp_secret_encrypted == REENROL
    assert row.enabled is True
