"""TC-16-006 gap 1: flag changes are audited, and production env vars do not override rows.

The backlog command is ``python -m pytest tests/release/test_feature_flags.py -q``
from ``apps/api``.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit_event import AuditEvent
from app.models.feature_flag import FeatureFlag
from app.services.feature_flags import get_all_flags, is_enabled, set_flag

FLAG_UPDATED_ACTION = "feature_flag.updated"
AUDIT_FLAG = "release.tc16006.audit"
DENIED_FLAG = "release.tc16006.denied"
ENV_FLAG = "connectors.aws"
ENV_VAR = "FEATURE_CONNECTORS_AWS"


def _login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _login_admin(client: TestClient) -> int:
    from app.core.database import SessionLocal
    from app.models import User, WorkspaceMember

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").one()
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
            .one()
        )
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
        user_id = user.id
    finally:
        db.close()
    _login(client, "demo@trust.local", "j")
    return user_id


def _delete_flag(flag_name: str, workspace_id: int = 1) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        db.query(FeatureFlag).filter(
            FeatureFlag.workspace_id == workspace_id,
            FeatureFlag.flag_name == flag_name,
        ).delete()
        db.commit()
    finally:
        db.close()


def _latest_audit_id() -> int:
    from sqlalchemy import func

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return int(db.query(func.max(AuditEvent.id)).scalar() or 0)
    finally:
        db.close()


def _events(flag_name: str, after_id: int) -> list[dict]:
    """Audit rows for ``flag_name`` with id greater than ``after_id``.

    Fields are copied out before the session closes. Earlier tests leave rows
    behind; the high-water mark keeps each test to its own writes.
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(AuditEvent)
            .filter(AuditEvent.action == FLAG_UPDATED_ACTION, AuditEvent.id > after_id)
            .order_by(AuditEvent.id.asc())
            .all()
        )
        matched: list[dict] = []
        for row in rows:
            details = json.loads(row.details) if row.details else {}
            if details.get("flag_name") != flag_name:
                continue
            matched.append(
                {
                    "user_id": row.user_id,
                    "email": row.email,
                    "workspace_id": row.workspace_id,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "details": details,
                }
            )
        return matched
    finally:
        db.close()


def _one(flags: list[dict], flag_name: str) -> dict:
    return next(item for item in flags if item["flag_name"] == flag_name)


def test_flag_change_writes_audit_with_actor_old_and_new(client: TestClient) -> None:
    _delete_flag(AUDIT_FLAG)
    actor_id = _login_admin(client)

    mark = _latest_audit_id()
    created = client.patch("/api/feature-flags", json={"flag_name": AUDIT_FLAG, "enabled": False})
    assert created.status_code == 200, created.text
    updated = client.patch("/api/feature-flags", json={"flag_name": AUDIT_FLAG, "enabled": True})
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabled"] is True

    events = _events(AUDIT_FLAG, mark)
    assert len(events) == 2
    first, second = events
    assert first["user_id"] == actor_id
    assert first["email"] == "demo@trust.local"
    assert first["workspace_id"] == 1
    assert first["resource_type"] == "feature_flag"
    assert first["resource_id"] == AUDIT_FLAG
    assert first["details"]["old_enabled"] is None
    assert first["details"]["new_enabled"] is False
    assert first["details"]["changed"] is True

    assert second["user_id"] == actor_id
    assert second["email"] == "demo@trust.local"
    assert second["workspace_id"] == 1
    assert second["resource_type"] == "feature_flag"
    assert second["resource_id"] == AUDIT_FLAG
    assert second["details"]["flag_name"] == AUDIT_FLAG
    assert second["details"]["old_enabled"] is False
    assert second["details"]["new_enabled"] is True
    assert second["details"]["changed"] is True


def test_noop_flag_set_still_writes_one_audit(client: TestClient) -> None:
    """A repeat of the stored value is still one audit, and the row is not rewritten."""
    _delete_flag(AUDIT_FLAG)
    actor_id = _login_admin(client)
    mark = _latest_audit_id()
    first = client.patch("/api/feature-flags", json={"flag_name": AUDIT_FLAG, "enabled": True})
    assert first.status_code == 200, first.text
    again = client.patch("/api/feature-flags", json={"flag_name": AUDIT_FLAG, "enabled": True})
    assert again.status_code == 200, again.text
    assert again.json()["enabled"] is True

    events = _events(AUDIT_FLAG, mark)
    assert len(events) == 2
    assert events[1]["user_id"] == actor_id
    assert events[1]["details"]["old_enabled"] is True
    assert events[1]["details"]["new_enabled"] is True
    assert events[1]["details"]["changed"] is False

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(FeatureFlag)
            .filter(FeatureFlag.workspace_id == 1, FeatureFlag.flag_name == AUDIT_FLAG)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].enabled is True
    finally:
        db.close()


def test_non_admin_cannot_change_a_flag_and_writes_no_audit(client: TestClient) -> None:
    _delete_flag(DENIED_FLAG)
    _login(client, "reviewer@trust.local", "r")
    mark = _latest_audit_id()
    response = client.patch("/api/feature-flags", json={"flag_name": DENIED_FLAG, "enabled": True})
    assert response.status_code == 403
    assert _events(DENIED_FLAG, mark) == []

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        row = (
            db.query(FeatureFlag)
            .filter(FeatureFlag.workspace_id == 1, FeatureFlag.flag_name == DENIED_FLAG)
            .first()
        )
        assert row is None
    finally:
        db.close()


def test_rejected_flag_name_writes_no_audit(client: TestClient) -> None:
    _login_admin(client)
    mark = _latest_audit_id()
    response = client.patch("/api/feature-flags", json={"flag_name": " ", "enabled": True})
    assert response.status_code == 400
    assert _events("", mark) == []


def test_set_flag_commits_the_row_and_the_audit_together(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    """One commit covers the row and the audit. A second commit is the members.py pattern."""
    _delete_flag(AUDIT_FLAG)
    db_session.expire_all()
    calls = {"n": 0}
    real_commit = db_session.commit

    def _commit() -> None:
        calls["n"] += 1
        real_commit()

    monkeypatch.setattr(db_session, "commit", _commit)
    mark = _latest_audit_id()
    set_flag(db_session, 1, AUDIT_FLAG, True, actor_user_id=7, actor_email="actor@trust.test")
    assert calls["n"] == 1
    events = _events(AUDIT_FLAG, mark)
    assert len(events) == 1
    assert events[0]["user_id"] == 7
    assert events[0]["email"] == "actor@trust.test"
    assert events[0]["details"]["old_enabled"] is None
    assert events[0]["details"]["new_enabled"] is True
    assert is_enabled(db_session, 1, AUDIT_FLAG) is True


@pytest.mark.parametrize("app_env", ["production", " Production ", "PRODUCTION"])
def test_production_env_does_not_override_an_existing_row(
    client: TestClient, db_session: Session, monkeypatch, app_env: str
) -> None:
    _delete_flag(ENV_FLAG)
    db_session.expire_all()
    set_flag(db_session, 1, ENV_FLAG, False)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv(ENV_VAR, "1")
    get_settings.cache_clear()
    assert is_enabled(db_session, 1, ENV_FLAG) is False
    resolved = _one(get_all_flags(db_session, 1), ENV_FLAG)
    assert resolved["enabled"] is False
    assert resolved["source"] == "workspace"


def test_production_env_is_the_default_when_no_row_exists(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    _delete_flag(ENV_FLAG)
    _delete_flag("connectors.slack")
    db_session.expire_all()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(ENV_VAR, "1")
    monkeypatch.setenv("FEATURE_CONNECTORS_SLACK", "0")
    get_settings.cache_clear()

    assert is_enabled(db_session, 1, ENV_FLAG) is True
    aws = _one(get_all_flags(db_session, 1), ENV_FLAG)
    assert aws["enabled"] is True
    assert aws["source"] == "env"

    # connectors.slack defaults to enabled. The env var replaces that default.
    assert is_enabled(db_session, 1, "connectors.slack") is False
    slack = _one(get_all_flags(db_session, 1), "connectors.slack")
    assert slack["enabled"] is False
    assert slack["source"] == "env"


@pytest.mark.parametrize("app_env", ["development", "test", "staging"])
def test_outside_production_env_overrides_the_stored_row(
    client: TestClient, db_session: Session, monkeypatch, app_env: str
) -> None:
    _delete_flag(ENV_FLAG)
    db_session.expire_all()
    set_flag(db_session, 1, ENV_FLAG, False)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv(ENV_VAR, "1")
    get_settings.cache_clear()
    assert is_enabled(db_session, 1, ENV_FLAG) is True
    resolved = _one(get_all_flags(db_session, 1), ENV_FLAG)
    assert resolved["enabled"] is True
    assert resolved["source"] == "env"
