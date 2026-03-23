"""QA-201: Cross-workspace authorization tests. Users cannot read, mutate, or switch into workspaces they do not belong to."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, Workspace, WorkspaceMember


@pytest.fixture
def reviewer_user(db_session: Session) -> User:
    """Create a reviewer user in workspace 1 (same as demo workspace)."""
    email = "reviewer@trust.local"
    user = db_session.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            password_hash=hash_password("r"),
            display_name="Reviewer User",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    # Ensure membership as reviewer in workspace 1
    mem = (
        db_session.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
        .first()
    )
    if not mem:
        mem = WorkspaceMember(workspace_id=1, user_id=user.id, role="reviewer")
        db_session.add(mem)
        db_session.commit()
    else:
        mem.role = "reviewer"
        db_session.commit()
    return user


def test_documents_list_other_workspace_returns_403(client: TestClient) -> None:
    """Requesting another workspace's documents returns 403."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/documents/?workspace_id=2")
    assert r.status_code == 403
    assert "denied" in (r.json().get("detail") or "").lower() or "access" in (r.json().get("detail") or "").lower()


def test_questionnaires_list_other_workspace_returns_403(client: TestClient) -> None:
    """Requesting another workspace's questionnaires returns 403."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/questionnaires/?workspace_id=2")
    assert r.status_code == 403


def test_switch_workspace_non_member_returns_403(client: TestClient) -> None:
    """Switching to a workspace the user is not a member of returns 403."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    # Use workspace 3: demo is only in 1 and 2 (conftest); 3 exists but demo is not a member
    r = client.post("/api/auth/switch-workspace", json={"workspace_id": 3})
    assert r.status_code == 403
    assert "member" in (r.json().get("detail") or "").lower()


def test_reviewer_cannot_upload_document(
    client: TestClient, reviewer_user: User, db_session: Session
) -> None:
    """Reviewer role cannot upload documents (RBAC returns 403)."""
    r = client.post("/api/auth/login", json={"email": "reviewer@trust.local", "password": "r"})
    assert r.status_code == 200
    # Upload requires can_edit; reviewer has can_review only
    r2 = client.post(
        "/api/documents/upload",
        data={"workspace_id": 1},
        files={"file": ("test.pdf", b"fake pdf content", "application/pdf")},
    )
    assert r2.status_code == 403
    assert "permission" in (r2.json().get("detail") or "").lower() or "insufficient" in (r2.json().get("detail") or "").lower()


def test_reviewer_can_list_documents(client: TestClient, reviewer_user: User) -> None:
    """Reviewer can list documents (can_review)."""
    client.post("/api/auth/login", json={"email": "reviewer@trust.local", "password": "r"})
    r = client.get("/api/documents/?workspace_id=1")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_reviewer_cannot_trigger_export(client: TestClient, reviewer_user: User) -> None:
    """Reviewer cannot trigger export (can_export required)."""
    client.post("/api/auth/login", json={"email": "reviewer@trust.local", "password": "r"})
    r = client.post("/api/exports/generate/1?workspace_id=1")
    assert r.status_code == 403
