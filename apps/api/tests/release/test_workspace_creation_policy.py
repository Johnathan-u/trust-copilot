"""TC-04-001a: POST /api/workspaces follows the signup policy, a per-user cap and a throttle.

- Invitation-only (the default): only an existing workspace owner/admin or a deployment
  operator may create a workspace; any other signed-in user gets 403.
- Self-signup: any email-verified user may create one (this is also the first-workspace
  onboarding path after signup); unverified users get 403.
- A user may hold at most N owner/admin memberships (default 3); creating past it is 409.
- At most M creations per user per hour (default 5); past it is 429 with Retry-After.

All data is synthetic and removed after each test.
"""

import secrets
from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.password import hash_password
from app.models import User, Workspace, WorkspaceMember
from app.models.user_session import UserSession

PASSWORD = "example-synthetic-test-ws-create-pw"  # synthetic test credential
SEED_WORKSPACES = (1, 2, 3)
ENV_NAMES = (
    "SIGNUP_POLICY",
    "WORKSPACE_ADMIN_CAP_PER_USER",
    "WORKSPACE_CREATE_PER_HOUR",
    "DEPLOYMENT_OPERATOR_EMAILS",
)


@pytest.fixture(autouse=True)
def _policy_env(monkeypatch) -> Generator[None, None, None]:
    """Start every test from the defaults, whatever the host environment says."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_env(monkeypatch, **values: str) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


@pytest.fixture
def make_user(db_session: Session) -> Generator[Callable[..., User], None, None]:
    """Create a synthetic user with optional (workspace_id, role) memberships."""
    created: list[int] = []

    def _make(
        verified: bool = False,
        memberships: tuple[tuple[int, str], ...] = (),
        suspended: bool = False,
    ) -> User:
        email = f"ws-create-{secrets.token_hex(6)}@example.test"
        user = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            display_name="WS Create Test",
            email_verified=verified,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        created.append(user.id)
        for ws_id, role in memberships:
            db_session.add(
                WorkspaceMember(
                    workspace_id=ws_id, user_id=user.id, role=role, suspended=suspended
                )
            )
        db_session.commit()
        return user

    yield _make
    db_session.rollback()
    if created:
        ws_ids = [
            wid
            for (wid,) in db_session.query(WorkspaceMember.workspace_id)
            .filter(
                WorkspaceMember.user_id.in_(created),
                WorkspaceMember.workspace_id.notin_(SEED_WORKSPACES),
            )
            .all()
        ]
        db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id.in_(created)).delete(
            synchronize_session=False
        )
        if ws_ids:
            db_session.query(Workspace).filter(Workspace.id.in_(ws_ids)).delete(
                synchronize_session=False
            )
        db_session.query(UserSession).filter(UserSession.user_id.in_(created)).delete(
            synchronize_session=False
        )
        db_session.query(User).filter(User.id.in_(created)).delete(synchronize_session=False)
        db_session.commit()


def _login(client: TestClient, user: User) -> None:
    r = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert r.status_code == 200, r.text


def _create(client: TestClient, label: str = "ws"):
    return client.post("/api/workspaces", json={"name": f"Synthetic {label} {secrets.token_hex(4)}"})


def _admin_memberships(db: Session, user: User) -> int:
    db.expire_all()
    return (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.role == "admin")
        .count()
    )


def _assert_generic(detail: str) -> None:
    for name in ENV_NAMES:
        assert name not in detail
    assert "_" not in detail


# --- (1) signup policy -------------------------------------------------------------------


def test_default_policy_is_invitation_only() -> None:
    assert get_settings().signup_policy == "invitation_only"


def test_unknown_policy_value_fails_closed(monkeypatch) -> None:
    _set_env(monkeypatch, SIGNUP_POLICY="open-to-everyone")
    assert get_settings().signup_policy == "invitation_only"


@pytest.mark.parametrize(
    "memberships",
    [(), ((1, "editor"),), ((1, "reviewer"),)],
    ids=["no-membership", "editor", "reviewer"],
)
def test_invitation_only_denies_plain_user(
    client: TestClient, db_session: Session, make_user, memberships
) -> None:
    user = make_user(verified=True, memberships=memberships)
    _login(client, user)
    r = _create(client)
    assert r.status_code == 403, r.text
    _assert_generic(r.json()["detail"])
    assert _admin_memberships(db_session, user) == 0


def test_invitation_only_denies_suspended_admin(
    client: TestClient, db_session: Session, make_user
) -> None:
    user = make_user(verified=True, memberships=((2, "admin"),), suspended=True)
    # Log in through a non-suspended membership so the session itself is valid.
    db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="editor"))
    db_session.commit()
    _login(client, user)
    r = _create(client)
    assert r.status_code == 403, r.text


def test_invitation_only_allows_workspace_admin(
    client: TestClient, db_session: Session, make_user
) -> None:
    user = make_user(verified=False, memberships=((1, "admin"),))
    _login(client, user)
    r = _create(client, "admin")
    assert r.status_code == 200, r.text
    assert _admin_memberships(db_session, user) == 2
    me = client.get("/api/auth/me").json()
    assert me["workspace_id"] == r.json()["id"]


def test_invitation_only_allows_deployment_operator(
    client: TestClient, db_session: Session, make_user, monkeypatch
) -> None:
    user = make_user(verified=True)
    _set_env(monkeypatch, DEPLOYMENT_OPERATOR_EMAILS=f"other@example.test, {user.email.upper()}")
    _login(client, user)
    r = _create(client, "operator")
    assert r.status_code == 200, r.text
    assert _admin_memberships(db_session, user) == 1


def test_unverified_operator_email_is_not_an_operator(
    client: TestClient, make_user, monkeypatch
) -> None:
    user = make_user(verified=False)
    _set_env(monkeypatch, DEPLOYMENT_OPERATOR_EMAILS=user.email)
    _login(client, user)
    assert _create(client).status_code == 403


def test_self_signup_allows_verified_user_first_workspace(
    client: TestClient, db_session: Session, make_user, monkeypatch
) -> None:
    """TC-04-001 AC1 path: a verified new user with no workspace onboards into its own one."""
    _set_env(monkeypatch, SIGNUP_POLICY="self_signup")
    user = make_user(verified=True)
    r = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert r.status_code == 200 and r.json().get("needs_onboarding") is True
    r = _create(client, "first")
    assert r.status_code == 200, r.text
    ws_id = r.json()["id"]
    assert ws_id not in SEED_WORKSPACES
    me = client.get("/api/auth/me").json()
    assert me["workspace_id"] == ws_id
    assert _admin_memberships(db_session, user) == 1


def test_self_signup_denies_unverified_user(
    client: TestClient, db_session: Session, make_user, monkeypatch
) -> None:
    _set_env(monkeypatch, SIGNUP_POLICY="self_signup")
    user = make_user(verified=False)
    _login(client, user)
    r = _create(client)
    assert r.status_code == 403, r.text
    _assert_generic(r.json()["detail"])
    assert _admin_memberships(db_session, user) == 0


def test_unauthenticated_request_is_rejected(client: TestClient) -> None:
    assert _create(client).status_code == 401


# --- (2) per-user cap ----------------------------------------------------------------------


def test_cap_of_three_admin_workspaces(
    client: TestClient, db_session: Session, make_user, monkeypatch
) -> None:
    _set_env(monkeypatch, SIGNUP_POLICY="self_signup")
    user = make_user(verified=True)
    _login(client, user)
    for i in range(3):
        assert _create(client, f"cap{i}").status_code == 200
    r = _create(client, "cap-over")
    assert r.status_code == 409, r.text
    _assert_generic(r.json()["detail"])
    assert _admin_memberships(db_session, user) == 3


def test_cap_counts_existing_admin_memberships(
    client: TestClient, db_session: Session, make_user
) -> None:
    user = make_user(memberships=((1, "admin"), (2, "admin")))
    _login(client, user)
    assert _create(client, "cap-existing").status_code == 200
    assert _create(client, "cap-existing-over").status_code == 409
    assert _admin_memberships(db_session, user) == 3


def test_cap_is_configurable(client: TestClient, make_user, monkeypatch) -> None:
    _set_env(monkeypatch, SIGNUP_POLICY="self_signup", WORKSPACE_ADMIN_CAP_PER_USER="1")
    user = make_user(verified=True)
    _login(client, user)
    assert _create(client, "cfg").status_code == 200
    assert _create(client, "cfg-over").status_code == 409


def test_cap_applies_to_operators(client: TestClient, make_user, monkeypatch) -> None:
    user = make_user(verified=True)
    _set_env(monkeypatch, DEPLOYMENT_OPERATOR_EMAILS=user.email)
    _login(client, user)
    for i in range(3):
        assert _create(client, f"op{i}").status_code == 200
    assert _create(client, "op-over").status_code == 409


# --- (3) per-user throttle -----------------------------------------------------------------


def test_throttle_five_per_hour_with_retry_after(
    client: TestClient, db_session: Session, make_user, monkeypatch
) -> None:
    _set_env(monkeypatch, SIGNUP_POLICY="self_signup", WORKSPACE_ADMIN_CAP_PER_USER="20")
    user = make_user(verified=True)
    _login(client, user)
    for i in range(5):
        assert _create(client, f"rate{i}").status_code == 200
    r = _create(client, "rate-over")
    assert r.status_code == 429, r.text
    _assert_generic(r.json()["detail"])
    retry_after = int(r.headers["Retry-After"])
    assert 0 < retry_after <= 3600
    assert _admin_memberships(db_session, user) == 5


def test_throttle_is_per_user(client: TestClient, make_user, monkeypatch) -> None:
    _set_env(
        monkeypatch,
        SIGNUP_POLICY="self_signup",
        WORKSPACE_ADMIN_CAP_PER_USER="20",
        WORKSPACE_CREATE_PER_HOUR="1",
    )
    first, second = make_user(verified=True), make_user(verified=True)
    _login(client, first)
    assert _create(client, "u1").status_code == 200
    assert _create(client, "u1-over").status_code == 429
    _login(client, second)
    assert _create(client, "u2").status_code == 200
