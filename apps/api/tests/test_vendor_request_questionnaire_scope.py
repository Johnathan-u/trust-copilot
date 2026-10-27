"""TC-06-BUG-011 / TC-02-BUG-010: vendor request questionnaire_id is scoped to the workspace.

- POST /api/vendor-requests/ returns the same 404 for a questionnaire id that does not exist,
  belongs to another workspace, or is soft-deleted; it never returns 403 or 500 and creates no row.
- The public GET /api/vendor-response?token= only shows a questionnaire from the vendor
  request's own workspace, even for rows that already hold a cross-workspace reference.

All data is synthetic and removed after each test.
"""

import secrets
from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, VendorRequest, WorkspaceMember
from app.models.questionnaire import Question, Questionnaire

ADMIN_EMAIL = "admin-vr-scope@trust.local"
ADMIN_PASSWORD = "scope-a"
OWN_WS = 1
OTHER_WS = 2


@pytest.fixture
def scope_admin(db_session: Session) -> User:
    """Admin in workspace 1 only (not a member of workspace 2)."""
    user = db_session.query(User).filter(User.email == ADMIN_EMAIL).first()
    if not user:
        user = User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            display_name="Admin VR Scope",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    mem = (
        db_session.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == OWN_WS)
        .first()
    )
    if not mem:
        db_session.add(WorkspaceMember(workspace_id=OWN_WS, user_id=user.id, role="admin"))
    else:
        mem.role = "admin"
    db_session.commit()
    return user


@pytest.fixture
def questionnaires(db_session: Session) -> Generator[dict[str, int], None, None]:
    """Synthetic questionnaires: own (ws1), other (ws2), own soft-deleted, and a missing id."""
    rows = {
        "own": Questionnaire(
            workspace_id=OWN_WS, filename="scope-own.xlsx", status="parsed", display_id="QNR-SC-1"
        ),
        "other": Questionnaire(
            workspace_id=OTHER_WS,
            filename="scope-other-tenant.xlsx",
            status="parsed",
            display_id="QNR-SC-2",
        ),
        "own_deleted": Questionnaire(
            workspace_id=OWN_WS,
            filename="scope-own-deleted.xlsx",
            status="parsed",
            display_id="QNR-SC-3",
            deleted_at=datetime.now(timezone.utc),
        ),
    }
    db_session.add_all(rows.values())
    db_session.commit()
    ids = {k: v.id for k, v in rows.items()}
    for qid in ids.values():
        db_session.add(Question(questionnaire_id=qid, text="Synthetic question?", section="S"))
    db_session.commit()
    ids["missing"] = (db_session.query(func.max(Questionnaire.id)).scalar() or 0) + 100_000
    yield ids
    db_session.rollback()
    created = [ids["own"], ids["other"], ids["own_deleted"]]
    db_session.query(VendorRequest).filter(VendorRequest.questionnaire_id.in_(created)).delete(
        synchronize_session=False
    )
    db_session.query(Questionnaire).filter(Questionnaire.id.in_(created)).delete(
        synchronize_session=False
    )
    db_session.commit()


def _login(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200


def _create(client: TestClient, questionnaire_id: int):
    return client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "scope-vendor@example.com", "questionnaire_id": questionnaire_id},
    )


def _count_requests(db_session: Session) -> int:
    db_session.expire_all()
    return db_session.query(func.count(VendorRequest.id)).scalar() or 0


def test_other_workspace_questionnaire_returns_404(
    client: TestClient, db_session: Session, scope_admin: User, questionnaires: dict[str, int]
) -> None:
    _login(client)
    before = _count_requests(db_session)
    r = _create(client, questionnaires["other"])
    assert r.status_code == 404
    assert r.json() == {"detail": "Questionnaire not found"}
    assert _count_requests(db_session) == before


def test_missing_questionnaire_returns_404_not_500(
    client: TestClient, db_session: Session, scope_admin: User, questionnaires: dict[str, int]
) -> None:
    _login(client)
    before = _count_requests(db_session)
    r = _create(client, questionnaires["missing"])
    assert r.status_code == 404
    assert r.json() == {"detail": "Questionnaire not found"}
    assert _count_requests(db_session) == before


def test_soft_deleted_questionnaire_returns_404(
    client: TestClient, db_session: Session, scope_admin: User, questionnaires: dict[str, int]
) -> None:
    _login(client)
    r = _create(client, questionnaires["own_deleted"])
    assert r.status_code == 404
    assert r.json() == {"detail": "Questionnaire not found"}


def test_404_body_identical_for_missing_other_and_deleted(
    client: TestClient, scope_admin: User, questionnaires: dict[str, int]
) -> None:
    """No existence oracle: same status, body and content type for every unusable id."""
    _login(client)
    responses = [_create(client, questionnaires[k]) for k in ("missing", "other", "own_deleted")]
    assert {r.status_code for r in responses} == {404}
    assert len({r.content for r in responses}) == 1
    assert len({r.headers.get("content-type") for r in responses}) == 1


def test_own_workspace_questionnaire_works_and_public_link_shows_it(
    client: TestClient, scope_admin: User, questionnaires: dict[str, int]
) -> None:
    _login(client)
    r = _create(client, questionnaires["own"])
    assert r.status_code == 200
    data = r.json()
    assert data["workspace_id"] == OWN_WS
    assert data["questionnaire_id"] == questionnaires["own"]

    client.cookies.clear()
    pub = client.get("/api/vendor-response", params={"token": data["link_token"]})
    assert pub.status_code == 200
    assert pub.json()["questionnaire"] == {"name": "scope-own.xlsx", "question_count": 1}


def test_create_without_questionnaire_still_works(client: TestClient, scope_admin: User) -> None:
    _login(client)
    r = client.post("/api/vendor-requests/", json={"vendor_email": "scope-noq@example.com"})
    assert r.status_code == 200
    assert r.json()["questionnaire_id"] is None


@pytest.mark.parametrize("which", ["other", "own_deleted"])
def test_public_link_hides_out_of_scope_questionnaire_in_existing_row(
    client: TestClient, db_session: Session, questionnaires: dict[str, int], which: str
) -> None:
    """A row written before the fix (cross-workspace or now-deleted FK) reveals nothing."""
    token = secrets.token_urlsafe(32)
    vr = VendorRequest(
        workspace_id=OWN_WS,
        vendor_email="legacy-row@example.com",
        questionnaire_id=questionnaires[which],
        message="Synthetic legacy row",
        status="pending",
        link_token=token,
    )
    db_session.add(vr)
    db_session.commit()

    client.cookies.clear()
    r = client.get("/api/vendor-response", params={"token": token})
    assert r.status_code == 200
    data = r.json()
    assert data == {"status": "pending", "message": "Synthetic legacy row", "questionnaire": None}
    assert "scope-" not in r.text
