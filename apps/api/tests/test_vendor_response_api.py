"""Public vendor-response endpoint tests — token resolution for vendor-facing landing page."""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, VendorRequest, WorkspaceMember
from app.models.questionnaire import Question, Questionnaire


@pytest.fixture
def admin_user(db_session: Session) -> User:
    email = "admin-vr@trust.local"
    user = db_session.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, password_hash=hash_password("a"), display_name="Admin VR")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    mem = db_session.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1
    ).first()
    if not mem:
        db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="admin"))
        db_session.commit()
    return user


@pytest.fixture
def vendor_request_with_qnr(db_session: Session):
    """VendorRequest linked to a questionnaire with questions."""
    qnr = Questionnaire(
        workspace_id=1,
        filename="vendor-test-questionnaire.xlsx",
        status="parsed",
        display_id="QNR-VR-TEST",
    )
    db_session.add(qnr)
    db_session.commit()
    db_session.refresh(qnr)

    for text in ["What is your data retention policy?", "Describe your encryption standards."]:
        db_session.add(Question(questionnaire_id=qnr.id, text=text, section="S", answer_type="text"))
    db_session.commit()

    token = secrets.token_urlsafe(32)
    vr = VendorRequest(
        workspace_id=1,
        vendor_email="vendor@example.com",
        questionnaire_id=qnr.id,
        message="Please complete this by Friday.",
        status="pending",
        link_token=token,
    )
    db_session.add(vr)
    db_session.commit()
    db_session.refresh(vr)

    try:
        yield vr, qnr
    finally:
        db_session.query(VendorRequest).filter(VendorRequest.id == vr.id).delete(synchronize_session=False)
        db_session.query(Question).filter(Question.questionnaire_id == qnr.id).delete(synchronize_session=False)
        db_session.query(Questionnaire).filter(Questionnaire.id == qnr.id).delete(synchronize_session=False)
        db_session.commit()


@pytest.fixture
def vendor_request_no_qnr(db_session: Session):
    """VendorRequest with no questionnaire attached."""
    token = secrets.token_urlsafe(32)
    vr = VendorRequest(
        workspace_id=1,
        vendor_email="noq@example.com",
        message=None,
        status="pending",
        link_token=token,
    )
    db_session.add(vr)
    db_session.commit()
    db_session.refresh(vr)
    try:
        yield vr
    finally:
        db_session.query(VendorRequest).filter(VendorRequest.id == vr.id).delete(synchronize_session=False)
        db_session.commit()


# ── Token validation ──────────────────────────────────────────────────────

def test_invalid_token_returns_404(client: TestClient) -> None:
    r = client.get("/api/vendor-response", params={"token": "totally-bogus-token-that-does-not-exist"})
    assert r.status_code == 404
    assert "invalid" in r.json()["detail"].lower() or "expired" in r.json()["detail"].lower()


def test_missing_token_returns_422(client: TestClient) -> None:
    r = client.get("/api/vendor-response")
    assert r.status_code == 422


def test_short_token_returns_422(client: TestClient) -> None:
    r = client.get("/api/vendor-response", params={"token": "abc"})
    assert r.status_code == 422


# ── No auth required ──────────────────────────────────────────────────────

def test_no_auth_required(client: TestClient, vendor_request_with_qnr) -> None:
    """Endpoint works without any login session."""
    vr, _ = vendor_request_with_qnr
    r = client.get("/api/vendor-response", params={"token": vr.link_token})
    assert r.status_code == 200


# ── Response shape ────────────────────────────────────────────────────────

def test_response_with_questionnaire(client: TestClient, vendor_request_with_qnr) -> None:
    vr, qnr = vendor_request_with_qnr
    r = client.get("/api/vendor-response", params={"token": vr.link_token})
    assert r.status_code == 200
    data = r.json()

    assert data["status"] == "pending"
    assert data["message"] == "Please complete this by Friday."
    assert data["questionnaire"] is not None
    assert data["questionnaire"]["name"] == "vendor-test-questionnaire.xlsx"
    assert data["questionnaire"]["question_count"] == 2

    assert "workspace_id" not in data
    assert "id" not in data
    assert "vendor_email" not in data
    assert "link_token" not in data


def test_response_without_questionnaire(client: TestClient, vendor_request_no_qnr) -> None:
    vr = vendor_request_no_qnr
    r = client.get("/api/vendor-response", params={"token": vr.link_token})
    assert r.status_code == 200
    data = r.json()

    assert data["status"] == "pending"
    assert data["message"] is None
    assert data["questionnaire"] is None

    assert "workspace_id" not in data
    assert "id" not in data
    assert "vendor_email" not in data


def test_no_internal_fields_exposed(client: TestClient, vendor_request_with_qnr) -> None:
    """Response must not leak workspace_id, id, vendor_email, link_token, or created_at."""
    vr, _ = vendor_request_with_qnr
    r = client.get("/api/vendor-response", params={"token": vr.link_token})
    data = r.json()
    forbidden = {"workspace_id", "id", "vendor_email", "link_token", "created_at", "questionnaire_id"}
    assert forbidden.isdisjoint(set(data.keys()))


# ── Status reflected ──────────────────────────────────────────────────────

def test_completed_status_reflected(client: TestClient, db_session: Session, vendor_request_with_qnr) -> None:
    vr, _ = vendor_request_with_qnr
    vr.status = "completed"
    db_session.commit()

    r = client.get("/api/vendor-response", params={"token": vr.link_token})
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


def test_in_progress_status_reflected(client: TestClient, db_session: Session, vendor_request_with_qnr) -> None:
    vr, _ = vendor_request_with_qnr
    vr.status = "in_progress"
    db_session.commit()

    r = client.get("/api/vendor-response", params={"token": vr.link_token})
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"


# ── End-to-end: create via admin → resolve via public ─────────────────────

def test_create_then_resolve_e2e(client: TestClient, admin_user: User) -> None:
    """Full flow: admin creates request → public endpoint resolves the token."""
    client.post("/api/auth/login", json={"email": admin_user.email, "password": "a"})
    cr = client.post("/api/vendor-requests/", json={
        "vendor_email": "e2e-resolve@vendor.com",
        "message": "End-to-end resolution test",
    })
    assert cr.status_code in (200, 201)
    token = cr.json()["link_token"]
    assert token

    r = client.get("/api/vendor-response", params={"token": token})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "pending"
    assert data["message"] == "End-to-end resolution test"
