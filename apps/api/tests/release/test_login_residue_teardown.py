"""TC-02-TEST-001: admin logins must not leave sessions or auth.login rows behind.

The second test has to run after the first. It reads the counts the first test
recorded, after that test's autouse teardown has removed the rows it created.
"""

from sqlalchemy import text

_baseline: dict[str, tuple[int, int]] = {}


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


def test_admin_logins_create_sessions_and_audit_rows(client):
    """Three admin logins, the same shape as the shared login fixtures, add rows."""
    before = _counts()
    assert before is not None
    _baseline["counts"] = before
    for _ in range(3):
        client.cookies.clear()
        response = client.post(
            "/api/auth/login",
            json={"email": "admin@trust.local", "password": "a"},
        )
        assert response.status_code == 200, response.text
    during = _counts()
    assert during is not None
    assert during[0] >= before[0] + 3
    assert during[1] >= before[1] + 3


def test_after_teardown_session_and_audit_counts_match_baseline():
    """After the previous test's teardown, both counts are back at its baseline."""
    assert "counts" in _baseline
    assert _counts() == _baseline["counts"]
