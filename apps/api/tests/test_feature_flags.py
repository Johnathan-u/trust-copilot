"""Tests for the per-workspace feature flag system (P0-09)."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.feature_flag import FeatureFlag
from app.services.feature_flags import (
    KNOWN_FLAGS,
    get_all_flags,
    is_enabled,
    seed_defaults,
    set_flag,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_admin(client: TestClient) -> None:
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1
        ).first()
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200


def _cleanup_flags(workspace_id: int = 1) -> None:
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        db.query(FeatureFlag).filter(FeatureFlag.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Unit tests (service layer)
# ---------------------------------------------------------------------------

class TestServiceLayer:
    def test_is_enabled_default(self, db_session: Session) -> None:
        _cleanup_flags()
        result = is_enabled(db_session, 1, "connectors.slack")
        default, _ = KNOWN_FLAGS["connectors.slack"]
        assert result == default

    def test_is_enabled_unknown_flag_defaults_false(self, db_session: Session) -> None:
        assert is_enabled(db_session, 1, "nonexistent.flag.xyz") is False

    def test_set_flag_creates_row(self, db_session: Session) -> None:
        _cleanup_flags()
        result = set_flag(db_session, 1, "connectors.aws", True)
        assert result["enabled"] is True
        assert result["source"] == "workspace"
        assert is_enabled(db_session, 1, "connectors.aws") is True

    def test_set_flag_updates_existing(self, db_session: Session) -> None:
        _cleanup_flags()
        set_flag(db_session, 1, "connectors.aws", True)
        set_flag(db_session, 1, "connectors.aws", False)
        assert is_enabled(db_session, 1, "connectors.aws") is False

    def test_env_override_takes_precedence(self, db_session: Session) -> None:
        _cleanup_flags()
        set_flag(db_session, 1, "connectors.aws", False)
        with patch.dict(os.environ, {"FEATURE_CONNECTORS_AWS": "1"}):
            assert is_enabled(db_session, 1, "connectors.aws") is True

    def test_seed_defaults_creates_all_known(self, db_session: Session) -> None:
        _cleanup_flags()
        count = seed_defaults(db_session, 1)
        assert count == len(KNOWN_FLAGS)
        count2 = seed_defaults(db_session, 1)
        assert count2 == 0

    def test_get_all_flags_returns_all_known(self, db_session: Session) -> None:
        _cleanup_flags()
        flags = get_all_flags(db_session, 1)
        names = {f["flag_name"] for f in flags}
        for known in KNOWN_FLAGS:
            assert known in names

    def test_get_all_flags_shows_source(self, db_session: Session) -> None:
        _cleanup_flags()
        flags = get_all_flags(db_session, 1)
        for f in flags:
            assert f["source"] == "default"
        set_flag(db_session, 1, "connectors.aws", True)
        flags = get_all_flags(db_session, 1)
        aws = next(f for f in flags if f["flag_name"] == "connectors.aws")
        assert aws["source"] == "workspace"
        assert aws["enabled"] is True

    def test_workspace_isolation(self, db_session: Session) -> None:
        _cleanup_flags(1)
        _cleanup_flags(2)
        set_flag(db_session, 1, "connectors.aws", True)
        assert is_enabled(db_session, 1, "connectors.aws") is True
        assert is_enabled(db_session, 2, "connectors.aws") is False


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

class TestFeatureFlagAPI:
    def test_list_flags_requires_admin(self, client: TestClient) -> None:
        client.post("/api/auth/login", json={"email": "reviewer@trust.local", "password": "r"})
        r = client.get("/api/feature-flags")
        assert r.status_code == 403

    def test_list_flags(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_flags()
        r = client.get("/api/feature-flags")
        assert r.status_code == 200
        data = r.json()
        assert "flags" in data
        assert len(data["flags"]) >= len(KNOWN_FLAGS)

    def test_get_single_flag(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/feature-flags/connectors.slack")
        assert r.status_code == 200
        assert r.json()["flag_name"] == "connectors.slack"
        assert "enabled" in r.json()

    def test_set_flag(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_flags()
        r = client.patch("/api/feature-flags", json={"flag_name": "connectors.aws", "enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        r2 = client.get("/api/feature-flags/connectors.aws")
        assert r2.json()["enabled"] is True

    def test_set_flag_toggle_off(self, client: TestClient) -> None:
        _login_admin(client)
        client.patch("/api/feature-flags", json={"flag_name": "connectors.aws", "enabled": True})
        client.patch("/api/feature-flags", json={"flag_name": "connectors.aws", "enabled": False})
        r = client.get("/api/feature-flags/connectors.aws")
        assert r.json()["enabled"] is False

    def test_set_flag_invalid_name(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.patch("/api/feature-flags", json={"flag_name": "", "enabled": True})
        assert r.status_code == 400

    def test_seed_defaults(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_flags()
        r = client.post("/api/feature-flags/seed")
        assert r.status_code == 200
        assert r.json()["created"] == len(KNOWN_FLAGS)
        r2 = client.post("/api/feature-flags/seed")
        assert r2.json()["created"] == 0

    def test_custom_flag(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.patch("/api/feature-flags", json={"flag_name": "custom.my_experiment", "enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        r2 = client.get("/api/feature-flags")
        names = [f["flag_name"] for f in r2.json()["flags"]]
        assert "custom.my_experiment" in names
