"""TC-25-001: dashboard card revision and a create that can be retried.

A custom card is a workspace row. PATCH must send the ``updated_at`` the
editor loaded. A different value is 409 and the stored row stays as it was.
Built-in cards are not rows, so the list gives them no id and no revision.

POST accepts an Idempotency-Key. The same key and body return the first card
and do not insert another. A new process reads that card from
GET /api/dashboard/cards. Fixtures are synthetic titles.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import SessionLocal
from app.models.dashboard_card import DashboardCard


def _login_admin(client: TestClient) -> None:
    from app.models import User, WorkspaceMember

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
            .first()
        )
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    response = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert response.status_code == 200


def _make_editor(client: TestClient) -> None:
    from app.models import User, WorkspaceMember

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
            .first()
        )
        mem.role = "editor"
        db.commit()
    finally:
        db.close()
    response = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert response.status_code == 200


def _cleanup() -> None:
    from app.models import CustomRole

    db = SessionLocal()
    try:
        db.query(DashboardCard).delete()
        db.query(CustomRole).filter(CustomRole.name.in_(("card_reviewer", "card_reader"))).delete()
        db.execute(
            text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :prefix"),
            {"prefix": "%dashboard-cards:create%"},
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_cards():
    _cleanup()
    yield
    _cleanup()
    _login_admin_quiet()


def _login_admin_quiet() -> None:
    """Put the shared demo membership back to admin for later tests."""
    from app.models import User, WorkspaceMember

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        if user is None:
            return
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
            .first()
        )
        if mem is not None and mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()


def _body(title: str, route: str = "/dashboard/documents", **extra) -> dict:
    payload = {
        "title": title,
        "description": "Synthetic card",
        "icon": "document",
        "target_route": route,
    }
    payload.update(extra)
    return payload


def _customs(client: TestClient) -> list[dict]:
    response = client.get("/api/dashboard/cards")
    assert response.status_code == 200, response.text
    return [card for card in response.json()["cards"] if not card.get("is_builtin")]


def _stored(card_id: int) -> DashboardCard:
    db = SessionLocal()
    try:
        row = db.get(DashboardCard, card_id)
        assert row is not None
        db.expunge(row)
        return row
    finally:
        db.close()


def _count_title(title: str) -> int:
    db = SessionLocal()
    try:
        return db.query(DashboardCard).filter(DashboardCard.title == title).count()
    finally:
        db.close()


def _list_in_new_process() -> dict:
    """GET the card list from a new interpreter. That process has no request memory."""
    code = """
import json
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(
    app,
    base_url="http://localhost",
    headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
)
login = client.post(
    "/api/auth/login",
    json={"email": "demo@trust.local", "password": "j"},
)
if login.status_code != 200:
    raise SystemExit("login failed")
response = client.get("/api/dashboard/cards")
if response.status_code != 200:
    raise SystemExit("list failed")
print("TC25001_LIST " + json.dumps(response.json()))
"""
    api_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=api_root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-800:]
    line = next(item for item in completed.stdout.splitlines() if item.startswith("TC25001_LIST "))
    return json.loads(line.removeprefix("TC25001_LIST "))


def test_builtin_cards_have_no_revision(client: TestClient):
    """Built-in cards are not rows. The list does not give them an id or updated_at."""
    _login_admin(client)
    response = client.get("/api/dashboard/cards")
    assert response.status_code == 200
    builtins = [card for card in response.json()["cards"] if card.get("is_builtin")]
    assert len(builtins) == 4
    for card in builtins:
        assert "id" not in card
        assert "updated_at" not in card
        assert card["target_route"].startswith("/dashboard/")


def test_patch_requires_the_loaded_revision_and_conflict_keeps_the_row(client: TestClient):
    """The first writer stores the new title. A second writer with the old revision is 409."""
    _login_admin(client)
    created = client.post("/api/dashboard/cards", json=_body("Loaded title"))
    assert created.status_code == 200, created.text
    card = created.json()
    loaded = card["updated_at"]
    assert isinstance(loaded, str) and loaded

    missing = client.patch(f"/api/dashboard/cards/{card['id']}", json={"title": "No revision"})
    assert missing.status_code == 422
    assert _stored(card["id"]).title == "Loaded title"

    first = client.patch(
        f"/api/dashboard/cards/{card['id']}",
        json={"title": "First write", "updated_at": loaded},
    )
    assert first.status_code == 200, first.text
    assert first.json()["title"] == "First write"
    assert first.json()["updated_at"] != loaded
    stored = _stored(card["id"])
    assert stored.title == "First write"
    assert stored.updated_at.isoformat() == first.json()["updated_at"]

    stale = client.patch(
        f"/api/dashboard/cards/{card['id']}",
        json={"title": "Second write", "updated_at": loaded},
    )
    assert stale.status_code == 409, stale.text
    assert "changed" in stale.json()["detail"].lower()
    kept = _stored(card["id"])
    assert kept.title == "First write"
    assert kept.updated_at.isoformat() == first.json()["updated_at"]
    listed = _customs(client)
    assert len(listed) == 1
    assert listed[0]["title"] == "First write"
    assert listed[0]["updated_at"] == first.json()["updated_at"]


def test_reorder_moves_the_revision_so_a_stale_edit_is_409(client: TestClient):
    """Reorder writes the row, so the loaded updated_at no longer matches."""
    _login_admin(client)
    created = client.post("/api/dashboard/cards", json=_body("Before reorder"))
    other = client.post(
        "/api/dashboard/cards", json=_body("Other card", route="/dashboard/exports")
    )
    card = created.json()
    loaded = card["updated_at"]
    reordered = client.post(
        "/api/dashboard/cards/reorder",
        json={"card_ids": [other.json()["id"], card["id"]]},
    )
    assert reordered.status_code == 200, reordered.text
    stale = client.patch(
        f"/api/dashboard/cards/{card['id']}",
        json={"title": "After reorder", "updated_at": loaded},
    )
    assert stale.status_code == 409, stale.text
    assert _stored(card["id"]).title == "Before reorder"


def test_editor_and_other_workspace_cannot_change_the_card(client: TestClient):
    """An editor is 403. Another workspace is 404. Neither write changes the row."""
    _login_admin(client)
    created = client.post("/api/dashboard/cards", json=_body("Kept title"))
    card = created.json()
    _make_editor(client)
    denied = client.patch(
        f"/api/dashboard/cards/{card['id']}",
        json={"title": "Editor write", "updated_at": card["updated_at"]},
    )
    assert denied.status_code == 403
    assert _stored(card["id"]).title == "Kept title"
    denied_create = client.post("/api/dashboard/cards", json=_body("Editor card"))
    assert denied_create.status_code == 403
    assert _count_title("Editor card") == 0

    _login_admin(client)
    from app.models import User, WorkspaceMember

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        mem2 = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 2)
            .first()
        )
        mem2.role = "admin"
        db.commit()
    finally:
        db.close()
    switched = client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
    assert switched.status_code == 200, switched.text
    foreign = client.patch(
        f"/api/dashboard/cards/{card['id']}",
        json={"title": "Other workspace", "updated_at": card["updated_at"]},
    )
    assert foreign.status_code == 404
    assert _stored(card["id"]).title == "Kept title"


def test_unknown_route_is_422_and_stores_nothing(client: TestClient):
    _login_admin(client)
    rejected = client.post(
        "/api/dashboard/cards",
        json=_body("Bad route", route="/not-a-dashboard-route"),
    )
    assert rejected.status_code == 422
    assert _count_title("Bad route") == 0


def test_retried_create_returns_the_same_card_after_restart(client: TestClient):
    """The same Idempotency-Key inserts one row. A new process lists that card."""
    _login_admin(client)
    title = f"Retry {uuid.uuid4().hex[:8]}"
    key = f"card-{uuid.uuid4().hex[:12]}"
    headers = {"Idempotency-Key": key}
    payload = _body(title, route="/dashboard/exports", icon="export")
    first = client.post("/api/dashboard/cards", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert "_request_hash" not in first.json()
    second = client.post("/api/dashboard/cards", json=payload, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["title"] == title
    assert second.json()["target_route"] == "/dashboard/exports"
    assert _count_title(title) == 1

    changed = dict(payload)
    changed["title"] = title + " other"
    conflict = client.post("/api/dashboard/cards", json=changed, headers=headers)
    assert conflict.status_code == 422
    assert "different request body" in conflict.json()["detail"]
    assert _count_title(title) == 1
    assert _count_title(title + " other") == 0

    invalid = client.post(
        "/api/dashboard/cards",
        json=payload,
        headers={"Idempotency-Key": "has space"},
    )
    assert invalid.status_code == 422
    assert _count_title(title) == 1

    listed = _list_in_new_process()
    builtins = [card for card in listed["cards"] if card.get("is_builtin")]
    customs = [card for card in listed["cards"] if not card.get("is_builtin")]
    assert len(builtins) == 4
    assert all("updated_at" not in card for card in builtins)
    assert len(customs) == 1
    assert customs[0]["id"] == first.json()["id"]
    assert customs[0]["title"] == title
    assert customs[0]["updated_at"] == first.json()["updated_at"]
    assert customs[0]["target_route"] == "/dashboard/exports"


def test_failed_create_releases_the_key(client: TestClient):
    """A rejected body does not insert a card, and the same key can then create one."""
    _login_admin(client)
    title = f"Corrected {uuid.uuid4().hex[:8]}"
    key = f"card-{uuid.uuid4().hex[:12]}"
    headers = {"Idempotency-Key": key}
    bad = client.post(
        "/api/dashboard/cards",
        json=_body(title, route="/not-a-dashboard-route"),
        headers=headers,
    )
    assert bad.status_code == 422
    assert _count_title(title) == 0
    created = client.post(
        "/api/dashboard/cards",
        json=_body(title, route="/dashboard/documents"),
        headers=headers,
    )
    assert created.status_code == 200, created.text
    replay = client.post(
        "/api/dashboard/cards",
        json=_body(title, route="/dashboard/documents"),
        headers=headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == created.json()["id"]
    assert _count_title(title) == 1
    listed = _customs(client)
    assert [card["id"] for card in listed] == [created.json()["id"]]


def _as_role(client: TestClient, role: str) -> None:
    from app.models import User, WorkspaceMember

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
            .first()
        )
        mem.role = role
        db.commit()
    finally:
        db.close()
    response = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert response.status_code == 200


def _grant_role(name: str, **flags: bool) -> None:
    from app.models import CustomRole

    values = {
        "can_edit": False,
        "can_review": False,
        "can_export": False,
        "can_admin": False,
    }
    values.update(flags)
    db = SessionLocal()
    try:
        db.query(CustomRole).filter(CustomRole.workspace_id == 1, CustomRole.name == name).delete()
        db.add(CustomRole(workspace_id=1, name=name, **values))
        db.commit()
    finally:
        db.close()


def test_route_permission_follows_the_application_nav():
    """The map is the nav flag for every allowed route, and nothing else."""
    from app.models.dashboard_card import ALLOWED_ROUTES, ROUTE_PERMISSION

    assert set(ROUTE_PERMISSION) == set(ALLOWED_ROUTES)
    assert ROUTE_PERMISSION["/dashboard/members"] == "can_admin"
    assert ROUTE_PERMISSION["/dashboard/notifications"] == "can_admin"
    assert ROUTE_PERMISSION["/dashboard/slack"] == "can_admin"
    assert ROUTE_PERMISSION["/dashboard/gmail"] == "can_admin"
    assert ROUTE_PERMISSION["/dashboard/audit"] == "can_admin"
    assert ROUTE_PERMISSION["/dashboard/ai-governance"] == "can_admin"
    assert ROUTE_PERMISSION["/dashboard/settings"] == "can_admin"
    assert ROUTE_PERMISSION["/dashboard/requests"] == "can_review"
    assert ROUTE_PERMISSION["/dashboard/documents"] is None
    assert ROUTE_PERMISSION["/dashboard/questionnaires"] is None
    assert ROUTE_PERMISSION["/dashboard/review"] is None
    assert ROUTE_PERMISSION["/dashboard/exports"] is None
    assert ROUTE_PERMISSION["/dashboard/compliance-gaps"] is None
    assert ROUTE_PERMISSION["/dashboard/trust-center"] is None
    assert ROUTE_PERMISSION["/dashboard/proof-chain"] is None
    assert ROUTE_PERMISSION["/dashboard/security"] is None


def test_list_drops_a_card_whose_route_the_caller_cannot_open(client: TestClient):
    """An editor keeps Documents and loses Members. A review role keeps Review."""
    _login_admin(client)
    created = {
        "documents": client.post(
            "/api/dashboard/cards", json=_body("Open documents", route="/dashboard/documents")
        ),
        "members": client.post(
            "/api/dashboard/cards", json=_body("Members link", route="/dashboard/members")
        ),
        "review": client.post(
            "/api/dashboard/cards", json=_body("Review link", route="/dashboard/review")
        ),
        "requests": client.post(
            "/api/dashboard/cards", json=_body("Requests link", route="/dashboard/requests")
        ),
    }
    assert all(response.status_code == 200 for response in created.values())

    _make_editor(client)
    editor_titles = {card["title"] for card in _customs(client)}
    assert "Open documents" in editor_titles
    assert "Review link" in editor_titles
    assert "Requests link" in editor_titles
    assert "Members link" not in editor_titles

    _grant_role("card_reviewer", can_review=True)
    _as_role(client, "card_reviewer")
    review_titles = {card["title"] for card in _customs(client)}
    assert "Review link" in review_titles
    assert "Open documents" in review_titles
    assert "Requests link" in review_titles
    assert "Members link" not in review_titles

    _grant_role("card_reader")
    _as_role(client, "card_reader")
    reader_titles = {card["title"] for card in _customs(client)}
    assert "Open documents" in reader_titles
    assert "Review link" in reader_titles
    assert "Requests link" not in reader_titles
    assert "Members link" not in reader_titles

    _login_admin(client)
    admin_titles = {card["title"] for card in _customs(client)}
    assert "Members link" in admin_titles
    assert "Requests link" in admin_titles
