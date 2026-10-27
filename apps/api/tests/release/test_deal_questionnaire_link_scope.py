"""TC-06-BUG-012: deal routes are scoped to the caller's workspace.

- POST /api/deals/{deal_id}/link-questionnaire returns the same 404 for a deal that does not exist
  or belongs to another workspace, and the same 404 for a questionnaire that does not exist,
  belongs to another workspace, or is soft-deleted. Nothing is linked in those cases.
- GET, PATCH, DELETE /api/deals/{deal_id} and GET /api/deals/{deal_id}/risk and /room return the
  same 404 for another workspace's deal as for a missing one, and leave that deal unchanged.
- The deal room and risk score only use questionnaires from the deal's own workspace, even for
  rows that already hold a cross-workspace link.

Two synthetic workspaces (1 and 2 from conftest); all data is synthetic and removed after each test.
"""

import json
from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, WorkspaceMember
from app.models.deal import Deal
from app.models.questionnaire import Question, Questionnaire

ADMIN_EMAIL = "admin-deal-scope@trust.local"
ADMIN_PASSWORD = "scope-d"
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
            display_name="Admin Deal Scope",
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
def admin(client: TestClient, scope_admin: User) -> TestClient:
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def data(db_session: Session) -> Generator[dict[str, int], None, None]:
    """Synthetic deals and questionnaires in workspaces 1 and 2, plus unused ids."""
    qnrs = {
        "q_own": Questionnaire(
            workspace_id=OWN_WS, filename="deal-scope-own.xlsx", status="parsed"
        ),
        "q_other": Questionnaire(
            workspace_id=OTHER_WS, filename="deal-scope-other-tenant.xlsx", status="parsed"
        ),
        "q_own_deleted": Questionnaire(
            workspace_id=OWN_WS,
            filename="deal-scope-own-deleted.xlsx",
            status="parsed",
            deleted_at=datetime.now(timezone.utc),
        ),
    }
    db_session.add_all(qnrs.values())
    db_session.commit()
    for q in qnrs.values():
        db_session.add(Question(questionnaire_id=q.id, text="Synthetic question?", section="S"))
    deals = {
        "d_own": Deal(workspace_id=OWN_WS, company_name="Deal Scope Own Co"),
        "d_other": Deal(
            workspace_id=OTHER_WS,
            company_name="Deal Scope Other Tenant Co",
            notes="other-tenant-note",
            linked_questionnaire_ids=json.dumps([qnrs["q_other"].id]),
        ),
    }
    db_session.add_all(deals.values())
    db_session.commit()
    ids = {k: v.id for k, v in {**qnrs, **deals}.items()}
    ids["q_missing"] = (db_session.query(func.max(Questionnaire.id)).scalar() or 0) + 100_000
    ids["d_missing"] = (db_session.query(func.max(Deal.id)).scalar() or 0) + 100_000
    yield ids
    db_session.rollback()
    db_session.query(Deal).filter(Deal.id.in_([ids["d_own"], ids["d_other"]])).delete(
        synchronize_session=False
    )
    q_ids = [ids["q_own"], ids["q_other"], ids["q_own_deleted"]]
    db_session.query(Question).filter(Question.questionnaire_id.in_(q_ids)).delete(
        synchronize_session=False
    )
    db_session.query(Questionnaire).filter(Questionnaire.id.in_(q_ids)).delete(
        synchronize_session=False
    )
    db_session.commit()


def _linked(db: Session, deal_id: int) -> list[int]:
    db.expire_all()
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    return json.loads(deal.linked_questionnaire_ids or "[]")


def _link(client: TestClient, deal_id: int, questionnaire_id: int):
    return client.post(
        f"/api/deals/{deal_id}/link-questionnaire", json={"questionnaire_id": questionnaire_id}
    )


def test_link_to_other_workspace_deal_is_404_like_missing(admin, db_session, data):
    before = _linked(db_session, data["d_other"])
    foreign = _link(admin, data["d_other"], data["q_own"])
    missing = _link(admin, data["d_missing"], data["q_own"])
    assert foreign.status_code == 404, foreign.text
    assert missing.status_code == 404, missing.text
    assert foreign.content == missing.content
    assert _linked(db_session, data["d_other"]) == before


@pytest.mark.parametrize("qkey", ["q_other", "q_missing", "q_own_deleted"])
def test_link_unknown_questionnaire_is_404(admin, db_session, data, qkey):
    r = _link(admin, data["d_own"], data[qkey])
    assert r.status_code == 404, r.text
    assert _linked(db_session, data["d_own"]) == []


def test_unknown_questionnaire_bodies_are_identical(admin, data):
    bodies = {
        k: _link(admin, data["d_own"], data[k]).content
        for k in ("q_other", "q_missing", "q_own_deleted")
    }
    assert len(set(bodies.values())) == 1, bodies


def test_link_own_questionnaire_to_own_deal(admin, db_session, data):
    r = _link(admin, data["d_own"], data["q_own"])
    assert r.status_code == 200, r.text
    assert r.json()["linked_questionnaire_ids"] == [data["q_own"]]
    assert _linked(db_session, data["d_own"]) == [data["q_own"]]
    # Linking again is idempotent.
    r = _link(admin, data["d_own"], data["q_own"])
    assert r.status_code == 200
    assert r.json()["linked_questionnaire_ids"] == [data["q_own"]]


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("get", "", None),
        ("get", "/risk", None),
        ("get", "/room", None),
        ("patch", "", {"notes": "changed"}),
        ("delete", "", None),
    ],
)
def test_other_workspace_deal_routes_are_404_like_missing(
    admin, db_session, data, method, suffix, body
):
    kwargs = {"json": body} if body is not None else {}
    foreign = getattr(admin, method)(f"/api/deals/{data['d_other']}{suffix}", **kwargs)
    missing = getattr(admin, method)(f"/api/deals/{data['d_missing']}{suffix}", **kwargs)
    assert foreign.status_code == 404, foreign.text
    assert missing.status_code == 404, missing.text
    assert foreign.content == missing.content
    db_session.expire_all()
    deal = db_session.query(Deal).filter(Deal.id == data["d_other"]).first()
    assert deal is not None
    assert deal.notes == "other-tenant-note"


def test_own_deal_routes_still_work(admin, data):
    deal_id = data["d_own"]
    assert admin.get(f"/api/deals/{deal_id}").status_code == 200
    assert admin.get(f"/api/deals/{deal_id}/risk").status_code == 200
    r = admin.patch(f"/api/deals/{deal_id}", json={"notes": "own-note"})
    assert r.status_code == 200 and r.json()["notes"] == "own-note"
    assert _link(admin, deal_id, data["q_own"]).status_code == 200
    room = admin.get(f"/api/deals/{deal_id}/room")
    assert room.status_code == 200, room.text
    assert [q["questionnaire_id"] for q in room.json()["questionnaires"]] == [data["q_own"]]


def test_room_and_risk_ignore_existing_cross_workspace_links(admin, db_session, data):
    """A row that already links another workspace's questionnaire does not expose it."""
    deal = db_session.query(Deal).filter(Deal.id == data["d_own"]).first()
    deal.linked_questionnaire_ids = json.dumps([data["q_other"], data["q_own_deleted"]])
    db_session.commit()
    room = admin.get(f"/api/deals/{data['d_own']}/room")
    assert room.status_code == 200, room.text
    assert room.json()["questionnaires"] == []
    assert "deal-scope-other-tenant" not in room.text
    risk = admin.get(f"/api/deals/{data['d_own']}/risk")
    assert risk.status_code == 200, risk.text
    assert risk.json()["breakdown"]["total_questions"] == 0
