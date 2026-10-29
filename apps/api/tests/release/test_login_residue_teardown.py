"""TC-02-TEST-001: admin logins must not leave sessions or auth.login rows behind.

Each test records its own baseline. None of them read state left by another test.
"""

import pytest
from sqlalchemy import text


def _counts() -> tuple[int, int]:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        sessions = db.execute(text("SELECT COUNT(*) FROM user_sessions")).scalar()
        audits = db.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE action = 'auth.login'")
        ).scalar()
        return int(sessions or 0), int(audits or 0)
    finally:
        db.close()


def _login(client) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@trust.local", "password": "a"},
    )
    assert response.status_code == 200, response.text


def test_admin_logins_create_sessions_and_audit_rows(client):
    """Three admin logins add user_sessions and auth.login rows."""
    before = _counts()
    for _ in range(3):
        _login(client)
    during = _counts()
    assert during[0] >= before[0] + 3
    assert during[1] >= before[1] + 3


def test_teardown_restores_sessions_and_auth_login_counts(client):
    """The teardown deletes only the rows this test created."""
    from tests.conftest import _login_residue_delete, _login_residue_snapshot

    before = _counts()
    bounds = _login_residue_snapshot()
    assert bounds is not None
    for _ in range(3):
        _login(client)
    during = _counts()
    assert during[0] >= before[0] + 3
    assert during[1] >= before[1] + 3
    _login_residue_delete(bounds)
    assert _counts() == before


def test_teardown_fails_when_audit_delete_trigger_exists():
    """A DELETE trigger on audit_events is not disabled. The teardown fails instead."""
    from app.core.database import SessionLocal
    from tests.conftest import _login_residue_delete, _login_residue_snapshot

    bounds = _login_residue_snapshot()
    assert bounds is not None
    db = SessionLocal()
    db.execute(text("DROP TRIGGER IF EXISTS tc_test001_block_audit_delete ON audit_events"))
    db.execute(text("DROP FUNCTION IF EXISTS tc_test001_block_audit_delete()"))
    db.execute(
        text(
            """
            CREATE FUNCTION tc_test001_block_audit_delete() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'audit delete blocked';
            END $$
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TRIGGER tc_test001_block_audit_delete
            BEFORE DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION tc_test001_block_audit_delete()
            """
        )
    )
    db.commit()
    try:
        with pytest.raises(pytest.fail.Exception, match="DELETE trigger or rule"):
            _login_residue_delete(bounds)
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS tc_test001_block_audit_delete ON audit_events"))
        db.execute(text("DROP FUNCTION IF EXISTS tc_test001_block_audit_delete()"))
        db.commit()
        db.close()
