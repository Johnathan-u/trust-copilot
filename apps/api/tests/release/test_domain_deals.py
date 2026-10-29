"""Typed deal amounts, dates, stage, owner, and tenant-scoped refs.

Synthetic rows only. Every row this module creates is removed, and the table
counts recorded at the start of each test are the same at the end.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.core.password import hash_password
from app.models.audit_event import AuditEvent
from app.models.deal import DEAL_SCHEMA, Deal
from app.models.document import Document
from app.models.questionnaire import Questionnaire
from app.models.shareable_space import ShareableSpace
from app.models.user import User, WorkspaceMember
from app.models.user_session import UserSession
from app.models.workspace import Workspace

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "tc23001_deal_types"
HOLD = "tc23001_deal_amount_hold"
HOLD_REASON = "float value is not exactly representable as numeric(18,2)"
AMOUNT = "990001.23"
CURRENCY = "XTS"
PASSWORD = "example-synthetic-tc23001"

READ_ROUTES = (
    ("GET", "/api/deals", None),
    ("GET", "/api/deals/analytics", None),
    ("GET", "/api/deals/revenue-unblocked", None),
    ("GET", "/api/deals/risk-ranking", None),
    ("GET", "/api/deals/upcoming-deadlines", None),
    ("GET", "/api/deals/overdue", None),
    ("GET", "/api/deals/at-risk-this-week", None),
    ("GET", "/api/deals/{deal_id}", None),
    ("GET", "/api/deals/{deal_id}/risk", None),
    ("GET", "/api/deals/{deal_id}/room", None),
)
WRITE_ROUTES = (
    (
        "POST",
        "/api/deals",
        {"company_name": "Denied Synthetic Co", "deal_value_arr": "1.00", "currency": CURRENCY},
    ),
    ("PATCH", "/api/deals/{deal_id}", {"notes": "denied"}),
    ("POST", "/api/deals/{deal_id}/link-questionnaire", {"questionnaire_id": 1}),
    ("POST", "/api/deals/{deal_id}/links", {"document_id": 1}),
    ("DELETE", "/api/deals/{deal_id}", None),
)


def _login(client: TestClient, email: str, password: str) -> TestClient:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client


def _call(client: TestClient, method: str, path: str, body: dict | None, deal_id: int):
    target = path.format(deal_id=deal_id)
    if body is None:
        return getattr(client, method.lower())(target)
    return getattr(client, method.lower())(target, json=body)


def _purge_user(db: Session, user_id: int, workspace_id: int) -> None:
    db.query(Deal).filter(Deal.workspace_id == workspace_id).delete(synchronize_session=False)
    db.execute(
        text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :prefix"),
        {"prefix": f"ws:{workspace_id}:%"},
    )
    db.query(AuditEvent).filter(AuditEvent.user_id == user_id).delete(synchronize_session=False)
    db.query(UserSession).filter(UserSession.user_id == user_id).delete(synchronize_session=False)
    db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.query(Workspace).filter(Workspace.id == workspace_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def isolated(client: TestClient, db_session: Session) -> Iterator[dict]:
    """A workspace with one admin and no other deals, so totals are exact."""
    token = uuid.uuid4().hex[:12]
    workspace = Workspace(name="Synthetic Deals", slug=f"tc23001-{token}")
    db_session.add(workspace)
    db_session.flush()
    user = User(
        email=f"tc23001-{token}@trust.local",
        password_hash=hash_password(PASSWORD),
        display_name="Synthetic Deal Admin",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin"))
    outsider = User(
        email=f"tc23001-out-{token}@trust.local",
        password_hash=hash_password(PASSWORD),
        display_name="Synthetic Other Member",
    )
    db_session.add(outsider)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=2, user_id=outsider.id, role="editor"))
    db_session.commit()
    _login(client, user.email, PASSWORD)
    try:
        yield {
            "client": client,
            "workspace_id": workspace.id,
            "user_id": user.id,
            "outsider_id": outsider.id,
        }
    finally:
        db_session.rollback()
        _purge_user(db_session, user.id, workspace.id)
        db_session.query(AuditEvent).filter(AuditEvent.user_id == outsider.id).delete(
            synchronize_session=False
        )
        db_session.query(UserSession).filter(UserSession.user_id == outsider.id).delete(
            synchronize_session=False
        )
        db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id == outsider.id).delete(
            synchronize_session=False
        )
        db_session.query(User).filter(User.id == outsider.id).delete(synchronize_session=False)
        db_session.commit()


def test_revision_is_an_ancestor_of_every_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert heads
    assert len(REVISION) <= 32
    # The revision is a head, or an ancestor of every head. The parent id is not pinned.

    def reaches(current: str | None, seen: set[str] | None = None) -> bool:
        walked: set[str] = set() if seen is None else seen
        while current and current not in walked:
            if current == REVISION:
                return True
            walked.add(current)
            down = script.get_revision(current).down_revision
            if isinstance(down, tuple):
                return all(reaches(item, set(walked)) for item in down)
            current = down
        return False

    assert all(reaches(head) for head in heads), (heads, REVISION)


def test_create_persists_typed_fields_across_restart_and_retry(isolated, db_session):
    client = isolated["client"]
    body = {
        "company_name": "Synthetic Buyer Co",
        "deal_value_arr": AMOUNT,
        "currency": CURRENCY,
        "stage": "evaluation",
        "expected_close_date": "2026-06-30",
        "actual_close_date": "2026-07-01",
        "owner_user_id": isolated["user_id"],
        "notes": "synthetic",
    }
    first = client.post("/api/deals", json=body, headers={"Idempotency-Key": "synthetic-create"})
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["schema_version"] == DEAL_SCHEMA
    assert payload["deal_value_arr"] == AMOUNT
    assert isinstance(payload["deal_value_arr"], str)
    assert payload["currency"] == CURRENCY
    assert payload["stage"] == "evaluation"
    assert payload["expected_close_date"] == "2026-06-30"
    assert payload["actual_close_date"] == "2026-07-01"
    assert payload["owner_user_id"] == isolated["user_id"]
    assert payload["close_date"].startswith("2026-06-30")
    second = client.post("/api/deals", json=body, headers={"Idempotency-Key": "synthetic-create"})
    assert second.status_code == 200, second.text
    assert second.json() == payload
    stored = db_session.query(Deal).filter(Deal.workspace_id == isolated["workspace_id"]).all()
    assert len(stored) == 1
    fresh = SessionLocal()
    try:
        row = fresh.execute(
            text(
                """
                SELECT deal_value_arr::text, currency, stage, expected_close_date::text,
                       actual_close_date::text, owner_user_id
                FROM deals WHERE id = :id
                """
            ),
            {"id": payload["id"]},
        ).one()
    finally:
        fresh.close()
    assert row == (AMOUNT, CURRENCY, "evaluation", "2026-06-30", "2026-07-01", isolated["user_id"])
    same_key_update = client.patch(
        f"/api/deals/{payload['id']}",
        json={"notes": "synthetic-updated"},
        headers={"Idempotency-Key": "synthetic-create"},
    )
    assert same_key_update.status_code == 200, same_key_update.text
    assert same_key_update.json()["notes"] == "synthetic-updated"
    assert same_key_update.json()["deal_value_arr"] == AMOUNT


def test_refs_validate_the_tenant_and_a_partial_failure_writes_nothing(isolated, db_session):
    client = isolated["client"]
    workspace_id = isolated["workspace_id"]
    questionnaire = Questionnaire(
        workspace_id=workspace_id, filename="synthetic-tc23001.xlsx", status="parsed"
    )
    foreign_questionnaire = Questionnaire(
        workspace_id=2, filename="synthetic-tc23001-other.xlsx", status="parsed"
    )
    document = Document(
        workspace_id=workspace_id,
        storage_key=f"synthetic/tc23001-{uuid.uuid4().hex}",
        filename="synthetic-tc23001.txt",
    )
    deleted = Document(
        workspace_id=workspace_id,
        storage_key=f"synthetic/tc23001-deleted-{uuid.uuid4().hex}",
        filename="synthetic-tc23001-deleted.txt",
        deleted_at=datetime.now(timezone.utc),
    )
    foreign_document = Document(
        workspace_id=2,
        storage_key=f"synthetic/tc23001-other-{uuid.uuid4().hex}",
        filename="synthetic-tc23001-other.txt",
    )
    room = ShareableSpace(workspace_id=workspace_id, name="Synthetic room")
    foreign_room = ShareableSpace(workspace_id=2, name="Synthetic other room")
    db_session.add_all(
        [
            questionnaire,
            foreign_questionnaire,
            document,
            deleted,
            foreign_document,
            room,
            foreign_room,
        ]
    )
    db_session.commit()
    created = client.post("/api/deals", json={"company_name": "Synthetic Link Co"})
    assert created.status_code == 200, created.text
    deal_id = created.json()["id"]
    try:
        linked = client.post(
            f"/api/deals/{deal_id}/links",
            json={
                "questionnaire_id": questionnaire.id,
                "document_id": document.id,
                "room_id": room.id,
            },
        )
        assert linked.status_code == 200, linked.text
        assert linked.json()["linked_questionnaire_ids"] == [questionnaire.id]
        assert linked.json()["linked_document_ids"] == [document.id]
        assert linked.json()["room_id"] == room.id

        def snapshot():
            db_session.expire_all()
            deal = db_session.query(Deal).filter(Deal.id == deal_id).one()
            return (
                deal.linked_questionnaire_ids,
                deal.linked_document_ids,
                deal.room_id,
                deal.updated_at,
            )

        before = snapshot()
        rejected = client.post(
            f"/api/deals/{deal_id}/links",
            json={"questionnaire_id": questionnaire.id, "document_id": foreign_document.id},
        )
        assert rejected.status_code == 404, rejected.text
        assert snapshot() == before

        pairs = {
            "questionnaire": (
                {"questionnaire_id": foreign_questionnaire.id},
                {"questionnaire_id": 9_900_000_001},
            ),
            "document": (
                {"document_id": foreign_document.id},
                {"document_id": deleted.id},
                {"document_id": 9_900_000_002},
            ),
            "room": ({"room_id": foreign_room.id}, {"room_id": 9_900_000_003}),
        }
        for bodies in pairs.values():
            contents = [
                client.post(f"/api/deals/{deal_id}/links", json=body).content for body in bodies
            ]
            assert len(set(contents)) == 1
            assert snapshot() == before

        missing_owner = client.patch(f"/api/deals/{deal_id}", json={"owner_user_id": 9_900_000_004})
        foreign_owner = client.patch(
            f"/api/deals/{deal_id}", json={"owner_user_id": isolated["outsider_id"]}
        )
        assert missing_owner.status_code == 404
        assert foreign_owner.status_code == 404
        assert missing_owner.content == foreign_owner.content
        assert snapshot() == before

        read = client.get(f"/api/deals/{deal_id}")
        assert read.status_code == 200
        assert snapshot()[3] == before[3]
    finally:
        db_session.rollback()
        db_session.query(Deal).filter(Deal.id == deal_id).delete(synchronize_session=False)
        for model, rows in (
            (Questionnaire, [questionnaire, foreign_questionnaire]),
            (Document, [document, deleted, foreign_document]),
            (ShareableSpace, [room, foreign_room]),
        ):
            db_session.query(model).filter(model.id.in_([row.id for row in rows])).delete(
                synchronize_session=False
            )
        db_session.commit()


def test_bad_amount_stage_and_ids_are_422(isolated):
    client = isolated["client"]
    float_amount = client.post(
        "/api/deals",
        json={"company_name": "Synthetic", "deal_value_arr": 10.1, "currency": CURRENCY},
    )
    assert float_amount.status_code == 422, float_amount.text
    bad_stage = client.post("/api/deals", json={"company_name": "Synthetic", "stage": "won"})
    assert bad_stage.status_code == 422, bad_stage.text
    bad_currency = client.post(
        "/api/deals",
        json={"company_name": "Synthetic", "deal_value_arr": AMOUNT, "currency": "us"},
    )
    assert bad_currency.status_code == 422, bad_currency.text
    missing_currency = client.post(
        "/api/deals", json={"company_name": "Synthetic", "deal_value_arr": AMOUNT}
    )
    assert missing_currency.status_code == 422, missing_currency.text
    boolean_id = client.post(
        "/api/deals", json={"company_name": "Synthetic", "owner_user_id": True}
    )
    assert boolean_id.status_code == 422, boolean_id.text


def test_analytics_use_stored_amounts_and_do_not_invent_a_win_rate(isolated):
    client = isolated["client"]
    empty = client.get("/api/deals/analytics")
    assert empty.status_code == 200, empty.text
    assert empty.json()["revenue_won"] == "0.00"
    assert empty.json()["revenue_pipeline"] == "0.00"
    assert empty.json()["win_rate"] is None
    assert empty.json()["total_deals"] == 0
    created = client.post(
        "/api/deals",
        json={
            "company_name": "Synthetic Won Co",
            "deal_value_arr": AMOUNT,
            "currency": CURRENCY,
            "stage": "closed_won",
        },
    )
    assert created.status_code == 200, created.text
    filled = client.get("/api/deals/analytics")
    assert filled.json()["revenue_won"] == AMOUNT
    assert filled.json()["win_rate"] == "100.0"
    assert filled.json()["closed_won"] == 1
    unblocked = client.get("/api/deals/revenue-unblocked")
    assert unblocked.json()["total_revenue_unblocked"] == AMOUNT
    assert unblocked.json()["details"][0]["value"] == AMOUNT


@pytest.mark.parametrize("method,path,body", READ_ROUTES)
def test_reads_allow_every_signed_in_role_and_reject_anonymous(
    method, path, body, client, db_session
):
    admin = _login(client, "admin@trust.local", "a")
    created = admin.post("/api/deals", json={"company_name": "Synthetic Read Co"})
    assert created.status_code == 200, created.text
    deal_id = created.json()["id"]
    try:
        for email, password in (
            ("admin@trust.local", "a"),
            ("editor@trust.local", "e"),
            ("reviewer@trust.local", "r"),
        ):
            actor = _login(client, email, password)
            response = _call(actor, method, path, body, deal_id)
            assert response.status_code == 200, response.text
        client.cookies.clear()
        anonymous = _call(client, method, path, body, deal_id)
        assert anonymous.status_code == 401, anonymous.text
    finally:
        db_session.rollback()
        db_session.query(Deal).filter(Deal.id == deal_id).delete(synchronize_session=False)
        db_session.commit()


@pytest.mark.parametrize("method,path,body", WRITE_ROUTES)
def test_writes_stay_admin_and_a_denial_changes_nothing(method, path, body, client, db_session):
    questionnaire = Questionnaire(
        workspace_id=1, filename="synthetic-tc23001-deny.xlsx", status="parsed"
    )
    document = Document(
        workspace_id=1,
        storage_key=f"synthetic/tc23001-deny-{uuid.uuid4().hex}",
        filename="synthetic-tc23001-deny.txt",
    )
    db_session.add_all([questionnaire, document])
    db_session.commit()
    deal_id = None
    try:
        if path.endswith("/link-questionnaire"):
            body = {"questionnaire_id": questionnaire.id}
        elif path.endswith("/links"):
            body = {"document_id": document.id}
        admin = _login(client, "admin@trust.local", "a")
        created = admin.post("/api/deals", json={"company_name": "Synthetic Write Co"})
        assert created.status_code == 200, created.text
        deal_id = created.json()["id"]
        before_deals = db_session.query(func.count(Deal.id)).scalar()
        before_keys = db_session.execute(text("SELECT count(*) FROM idempotency_keys")).scalar()
        client.cookies.clear()
        anonymous = _call(client, method, path, body, deal_id)
        assert anonymous.status_code == 401, anonymous.text
        for email, password in (("editor@trust.local", "e"), ("reviewer@trust.local", "r")):
            denied = _call(_login(client, email, password), method, path, body, deal_id)
            assert denied.status_code == 403, denied.text
        assert db_session.query(func.count(Deal.id)).scalar() == before_deals
        assert (
            db_session.execute(text("SELECT count(*) FROM idempotency_keys")).scalar()
            == before_keys
        )
        db_session.expire_all()
        kept = db_session.query(Deal).filter(Deal.id == deal_id).one()
        assert kept.company_name == "Synthetic Write Co"
        allowed = _call(_login(client, "admin@trust.local", "a"), method, path, body, deal_id)
        assert allowed.status_code == 200, allowed.text
    finally:
        db_session.rollback()
        db_session.query(Deal).filter(
            Deal.company_name.in_(["Synthetic Write Co", "Denied Synthetic Co"])
        ).delete(synchronize_session=False)
        db_session.query(Questionnaire).filter(Questionnaire.id == questionnaire.id).delete(
            synchronize_session=False
        )
        db_session.query(Document).filter(Document.id == document.id).delete(
            synchronize_session=False
        )
        db_session.execute(
            text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE 'ws:1:deals:%'")
        )
        db_session.commit()


def _migration_parent() -> str:
    """The parent named by the migration. Callers do not hard-code that id."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    parent = script.get_revision(REVISION).down_revision
    assert isinstance(parent, str) and parent
    return parent


def _deal_hold_counts() -> tuple[int, int]:
    session = SessionLocal()
    try:
        deals = session.execute(text("SELECT count(*) FROM deals")).scalar()
        hold = session.execute(text(f"SELECT count(*) FROM {HOLD}")).scalar()
        return int(deals or 0), int(hold or 0)
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _restored_deal_and_hold_counts():
    """Every test removes the deal and hold rows it creates."""
    before = _deal_hold_counts()
    yield
    assert _deal_hold_counts() == before


def _alembic(*args: str) -> str:
    env = {**os.environ, "TRUST_COPILOT_TESTING": "1"}
    engine.dispose()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    engine.dispose()
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def test_amount_backfill_downgrade_and_upgrade_round_trip():
    """A non-representable float is held, restored as the same text, then re-held."""
    before = _deal_hold_counts()
    parent = _migration_parent()
    _alembic("downgrade", parent)
    token = uuid.uuid4().hex[:8]
    session = SessionLocal()
    try:
        exact_id = session.execute(
            text(
                """
                INSERT INTO deals (
                    workspace_id, company_name, deal_value_arr, stage, close_date,
                    notes, created_at, updated_at
                )
                VALUES (
                    1, :name, 100000, 'prospect', '2026-04-15 12:30:00',
                    'exact', now(), now()
                )
                RETURNING id
                """
            ),
            {"name": f"Synthetic exact {token}"},
        ).scalar()
        inexact_id = session.execute(
            text(
                """
                INSERT INTO deals (
                    workspace_id, company_name, deal_value_arr, stage, close_date,
                    notes, created_at, updated_at
                )
                VALUES (
                    1, :name, (1.0/3.0)::float8, 'negotiation',
                    '2026-05-01 00:00:00', 'inexact', now(), now()
                )
                RETURNING id
                """
            ),
            {"name": f"Synthetic inexact {token}"},
        ).scalar()
        original_inexact = session.execute(
            text("SELECT deal_value_arr::text FROM deals WHERE id = :id"),
            {"id": inexact_id},
        ).scalar()
        session.commit()
        assert "." in original_inexact and len(original_inexact.split(".", 1)[1]) > 2
    finally:
        session.close()

    def read() -> dict[int, tuple]:
        fresh = SessionLocal()
        try:
            rows = fresh.execute(
                text(
                    """
                    SELECT id, company_name, stage, notes, close_date::text,
                           deal_value_arr::text
                    FROM deals WHERE id IN (:exact_id, :inexact_id)
                    ORDER BY id
                    """
                ),
                {"exact_id": exact_id, "inexact_id": inexact_id},
            ).all()
            return {row[0]: tuple(row[1:]) for row in rows}
        finally:
            fresh.close()

    def hold(deal_id: int):
        fresh = SessionLocal()
        try:
            return fresh.execute(
                text(
                    f"""
                    SELECT original_text, reason FROM {HOLD} WHERE deal_id = :id
                    """
                ),
                {"id": deal_id},
            ).one_or_none()
        finally:
            fresh.close()

    try:
        _alembic("upgrade", "head")
        upgraded = read()
        assert upgraded[exact_id][4] == "100000.00"
        assert upgraded[inexact_id][4] is None
        assert upgraded[exact_id][0].endswith(token)
        held = hold(inexact_id)
        assert held is not None
        assert held[0] == original_inexact
        assert held[1] == HOLD_REASON
        assert hold(exact_id) is None
        fresh = SessionLocal()
        try:
            expected = fresh.execute(
                text("SELECT expected_close_date::text FROM deals WHERE id = :id"),
                {"id": exact_id},
            ).scalar()
            currency = fresh.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'deals' AND column_name = 'currency'
                    """
                )
            ).scalar()
        finally:
            fresh.close()
        assert expected == "2026-04-15"
        assert currency == "currency"

        _alembic("downgrade", parent)
        downgraded = read()
        assert downgraded[exact_id][4] == "100000"
        assert downgraded[inexact_id][4] == original_inexact
        assert downgraded[exact_id][2] == "exact"
        fresh = SessionLocal()
        try:
            gone = fresh.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'deals' AND column_name = 'currency'
                    """
                )
            ).first()
        finally:
            fresh.close()
        assert gone is None

        _alembic("upgrade", "head")
        again = read()
        assert again[exact_id][4] == "100000.00"
        assert again[inexact_id][4] is None
        reheld = hold(inexact_id)
        assert reheld[0] == original_inexact
        assert reheld[1] == HOLD_REASON
        assert again[inexact_id][4] is None
    finally:
        _alembic("upgrade", "head")
        fresh = SessionLocal()
        try:
            fresh.execute(
                text(f"DELETE FROM {HOLD} WHERE deal_id IN (:exact_id, :inexact_id)"),
                {"exact_id": exact_id, "inexact_id": inexact_id},
            )
            fresh.execute(
                text("DELETE FROM deals WHERE id IN (:exact_id, :inexact_id)"),
                {"exact_id": exact_id, "inexact_id": inexact_id},
            )
            fresh.commit()
        finally:
            fresh.close()
    assert _deal_hold_counts() == before
    assert _deal_hold_counts() == before
