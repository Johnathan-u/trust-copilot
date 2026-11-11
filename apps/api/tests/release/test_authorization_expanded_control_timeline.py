"""TC-06-003g: timeline projections use current control/evidence ownership.

Real stored human authority and HTTP run on SQLite and migrated PostgreSQL.
Database guards stay enabled; any rejected unsafe fixture is verified separately.
"""

import hashlib
import json
import secrets
import warnings
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes.control_timeline import router
from app.core.database import get_db
from app.core.session import sign_session
from app.models import (
    ControlEvidenceLink,
    CustomRole,
    Document,
    EvidenceItem,
    Framework,
    FrameworkControl,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
from app.models.control_state import ControlStateSnapshot

MODELS = (
    User,
    Workspace,
    WorkspaceMember,
    UserSession,
    UserMfa,
    CustomRole,
    Framework,
    FrameworkControl,
    WorkspaceControl,
    Document,
    EvidenceItem,
    ControlEvidenceLink,
    ControlStateSnapshot,
)


def snapshot(db):
    return {
        model.__tablename__: hashlib.sha256(
            json.dumps(
                [
                    dict(row)
                    for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
                ],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def timeline(request, record_property):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        db = request.getfixturevalue("db_session")
        engine = db.get_bind()
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            for model in MODELS:
                connection.execute(CreateTable(model.__table__))
        db = Session(engine)
    before = snapshot(db)
    owned = {model: [] for model in MODELS}
    client = None

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        suffix = secrets.token_hex(8)
        workspaces = []
        for label in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if db.get(Workspace, wid) is None:
                    break
            workspaces.append(add(Workspace, id=wid, name=label, slug=f"timeline-{label}-{suffix}"))
        own, foreign = workspaces
        user = add(User, email=f"timeline-{suffix}@example.com", password_hash="synthetic-unused")
        other_user = add(
            User, email=f"timeline-other-{suffix}@example.com", password_hash="synthetic-unused"
        )
        member = add(WorkspaceMember, workspace_id=own.id, user_id=user.id, role="reviewer")
        sid = add(UserSession, user_id=user.id, session_id=f"timeline-{suffix}")
        add(
            CustomRole,
            workspace_id=own.id,
            name="timeline-no-flags",
            can_review=False,
            can_edit=False,
            can_export=False,
            can_admin=False,
        )
        controls = {
            label: add(
                WorkspaceControl,
                workspace_id=foreign.id if label == "foreign" else own.id,
                custom_name=f"Synthetic {label} control",
                status="not_implemented",
            )
            for label in ("own", "mixed", "foreign_only", "moving", "foreign")
        }
        controls["own"].status = "verified"
        controls["own"].verified_at = datetime(2026, 1, 4)
        controls["own"].verified_by_user_id = user.id
        controls["own"].last_reviewed_at = datetime(2026, 1, 3)
        evidence = {
            label: add(
                EvidenceItem,
                workspace_id=foreign.id if label == "foreign" else own.id,
                title=f"Synthetic {label} evidence",
                source_type="manual",
                source_metadata=json.dumps({"fixture": suffix, "label": label}),
                created_at=datetime(2026, 1, day),
            )
            for label, day in (("early", 1), ("late", 5), ("moving", 2), ("foreign", 20))
        }
        for control, item in (
            ("own", "early"),
            ("own", "late"),
            ("mixed", "early"),
            ("moving", "moving"),
        ):
            add(ControlEvidenceLink, control_id=controls[control].id, evidence_id=evidence[item].id)
        for day, status, previous, confidence, count in (
            (2, "not_assessed", None, 0, 0),
            (6, "passing", "failing", 80, 2),
        ):
            add(
                ControlStateSnapshot,
                workspace_id=own.id,
                control_id=controls["own"].id,
                status=status,
                previous_status=previous,
                confidence_score=confidence,
                evidence_count=count,
                evaluated_by="synthetic-reviewer",
                details_json=json.dumps({"fixture": suffix}),
                created_at=datetime(2026, 1, day),
            )
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        app.dependency_overrides[get_db] = database
        client = TestClient(app)

        def cookie(**overrides):
            options = {"session_id": sid.session_id, "max_age_seconds": 3600}
            options.update(overrides)
            client.cookies.clear()
            client.cookies.set(
                "tc_session", sign_session(user.id, user.email, own.id, "reviewer", **options)
            )

        cookie()
        yield {
            "db": db,
            "engine": engine,
            "client": client,
            "own": own,
            "foreign": foreign,
            "user": user,
            "other_user": other_user,
            "member": member,
            "sid": sid,
            "controls": controls,
            "evidence": evidence,
            "add": add,
            "cookie": cookie,
            "record_property": record_property,
        }
    finally:
        if client is not None:
            client.close()
        db.rollback()
        for model in reversed(MODELS):
            if owned[model]:
                db.query(model).filter(model.id.in_(owned[model])).delete(synchronize_session=False)
        db.commit()
        assert snapshot(db) == before, "Cleanup changed pre-existing rows"
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def attempt_owned_fixture_change(state, label, change):
    """A DB-enforced scope boundary is evidence, never a reason to disable it."""
    db = state["db"]
    before = snapshot(db)
    try:
        with db.begin_nested():
            change()
            db.flush()
        db.commit()
    except IntegrityError as exc:
        assert db.get_bind().dialect.name == "postgresql", "Unexpected SQLite fixture rejection"
        code = getattr(exc.orig, "pgcode", None)
        assert code in {
            "23503",
            "23514",
        }, "Unexpected database error, not a referential scope guard"
        db.expire_all()
        assert snapshot(db) == before, "Rejected fixture change was not atomic"
        state["record_property"]("database_scope_guard", f"{label}:{code}")
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        warnings.warn(
            f"TC-06-003g PostgreSQL protected {label}: SQLSTATE {code}, "
            f"constraint {constraint or 'unnamed'}; no unsafe row was constructed",
            stacklevel=2,
        )
        return False
    state["record_property"]("database_scope_guard", f"{label}:not-rejected")
    return True


def read(state, control_id, *, limit=50):
    before = snapshot(state["db"])
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(state["engine"], "before_cursor_execute", record)
    try:
        response = state["client"].get(f"/api/control-timeline/{control_id}?limit={limit}")
    finally:
        event.remove(state["engine"], "before_cursor_execute", record)
    state["db"].expire_all()
    assert snapshot(state["db"]) == before
    assert {sql.lstrip().split(None, 1)[0].upper() for sql in statements} <= {"SELECT"}
    state["statements"] = statements
    return response


def evidence_event(state, label, day):
    return {
        "type": "evidence_linked",
        "timestamp": f"2026-01-{day:02d}T00:00:00",
        "evidence_id": state["evidence"][label].id,
        "evidence_title": f"Synthetic {label} evidence",
    }


def simple_timeline(state, label, events):
    return {
        "control_id": state["controls"][label].id,
        "current_status": "not_implemented",
        "total_events": len(events),
        "drift_events": 0,
        "events": events,
    }


@pytest.mark.parametrize("limit", (1, 50))
def test_mixed_links_filter_foreign_metadata_before_count_sort_and_limit(timeline, limit):
    state = timeline
    attempt_owned_fixture_change(
        state,
        "mixed-link",
        lambda: state["add"](
            ControlEvidenceLink,
            control_id=state["controls"]["mixed"].id,
            evidence_id=state["evidence"]["foreign"].id,
        ),
    )
    response = read(state, state["controls"]["mixed"].id, limit=limit)
    assert response.status_code == 200
    assert response.json() == simple_timeline(state, "mixed", [evidence_event(state, "early", 1)])


def test_foreign_only_links_cannot_inflate_empty_timeline(timeline):
    state = timeline
    attempt_owned_fixture_change(
        state,
        "foreign-only-link",
        lambda: state["add"](
            ControlEvidenceLink,
            control_id=state["controls"]["foreign_only"].id,
            evidence_id=state["evidence"]["foreign"].id,
        ),
    )
    response = read(state, state["controls"]["foreign_only"].id)
    assert response.status_code == 200
    assert response.json() == simple_timeline(state, "foreign_only", [])


def test_evidence_moved_to_another_workspace_disappears_from_projection(timeline):
    state = timeline
    own_event = evidence_event(state, "moving", 2)
    assert read(state, state["controls"]["moving"].id).json() == simple_timeline(
        state, "moving", [own_event]
    )
    moved = attempt_owned_fixture_change(
        state,
        "move-evidence",
        lambda: setattr(
            state["evidence"]["moving"],
            "workspace_id",
            state["foreign"].id,
        ),
    )
    response = read(state, state["controls"]["moving"].id)
    assert response.status_code == 200
    assert response.json() == simple_timeline(state, "moving", [] if moved else [own_event])


def test_deleted_evidence_uses_real_fk_cascade(timeline):
    state = timeline
    cid = state["controls"]["moving"].id
    eid = state["evidence"]["moving"].id
    state["db"].delete(state["evidence"]["moving"])
    state["db"].commit()
    assert (
        state["db"]
        .query(ControlEvidenceLink)
        .filter(ControlEvidenceLink.evidence_id == eid)
        .count()
        == 0
    )
    response = read(state, cid)
    assert response.status_code == 200
    assert response.json() == simple_timeline(state, "moving", [])


@pytest.mark.parametrize("limit,total", ((1, 5), (2, 6), (50, 6)))
def test_own_state_evidence_review_and_verification_events_keep_existing_order(
    timeline, limit, total
):
    state = timeline
    response = read(state, state["controls"]["own"].id, limit=limit)
    assert response.status_code == 200
    actual = response.json()
    # PostgreSQL's timestamptz snapshots carry an offset; SQLite returns naive
    # timestamps. Compare their UTC instants without changing stored fixtures.
    for item in actual["events"]:
        dt = datetime.fromisoformat(item["timestamp"])
        item["timestamp"] = (
            (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc))
            .replace(tzinfo=None)
            .isoformat()
        )
    expected = [
        {
            "type": "state_change",
            "timestamp": "2026-01-06T00:00:00",
            "status": "passing",
            "previous_status": "failing",
            "confidence_score": 80,
            "evidence_count": 2,
            "evaluated_by": "synthetic-reviewer",
            "drift_detected": True,
        },
        evidence_event(state, "late", 5),
        {
            "type": "verified",
            "timestamp": "2026-01-04T00:00:00",
            "verified_by_user_id": state["user"].id,
        },
        {"type": "reviewed", "timestamp": "2026-01-03T00:00:00"},
        {
            "type": "state_change",
            "timestamp": "2026-01-02T00:00:00",
            "status": "not_assessed",
            "previous_status": None,
            "confidence_score": 0,
            "evidence_count": 0,
            "evaluated_by": "synthetic-reviewer",
            "drift_detected": False,
        },
        evidence_event(state, "early", 1),
    ]
    assert actual == {
        "control_id": state["controls"]["own"].id,
        "current_status": "verified",
        "total_events": total,
        "drift_events": 1,
        "events": expected[:limit],
    }


@pytest.mark.parametrize("parent", ("foreign", "missing", "moved", "deleted"))
def test_unavailable_control_keeps_neutral_404_before_child_queries(timeline, parent):
    state = timeline
    cid = state["controls"]["moving"].id
    if parent == "foreign":
        cid = state["controls"]["foreign"].id
    elif parent == "missing":
        cid = 2147483647
        assert state["db"].get(WorkspaceControl, cid) is None
    elif parent == "deleted":
        state["db"].delete(state["controls"]["moving"])
        state["db"].commit()
    else:
        moved = attempt_owned_fixture_change(
            state,
            "move-control",
            lambda: setattr(
                state["controls"]["moving"],
                "workspace_id",
                state["foreign"].id,
            ),
        )
        if not moved:
            response = read(state, cid)
            assert response.status_code == 200
            assert response.json() == simple_timeline(
                state, "moving", [evidence_event(state, "moving", 2)]
            )
            return
    response = read(state, cid)
    assert response.status_code == 404
    assert response.json() == {"detail": "Control not found"}
    assert not any(
        "control_state_snapshots" in sql
        or "control_evidence_links" in sql
        or "evidence_items" in sql
        for sql in state["statements"]
    )


@pytest.mark.parametrize(
    "authority,status",
    (
        ("anonymous", 401),
        ("expired", 401),
        ("revoked", 401),
        ("session_other_user", 401),
        ("suspended", 403),
        ("removed", 403),
        ("missing_workspace", 403),
    ),
)
def test_current_principal_denial_does_not_query_timeline_objects(timeline, authority, status):
    state = timeline
    cid = state["controls"]["own"].id
    if authority == "anonymous":
        state["client"].cookies.clear()
    elif authority == "expired":
        state["cookie"](max_age_seconds=-1)
    elif authority == "revoked":
        state["db"].delete(state["sid"])
    elif authority == "session_other_user":
        state["sid"].user_id = state["other_user"].id
    elif authority == "suspended":
        state["member"].suspended = True
    elif authority == "removed":
        state["db"].delete(state["member"])
    else:
        state["db"].delete(state["own"])
    state["db"].commit()
    response = read(state, cid)
    assert response.status_code == status
    assert set(response.json()) == {"detail"}
    assert not any(
        "workspace_controls" in sql or "evidence_items" in sql or "control_state_snapshots" in sql
        for sql in state["statements"]
    )


@pytest.mark.parametrize("role", ("admin", "editor", "reviewer", "timeline-no-flags"))
def test_existing_session_only_read_permission_is_preserved(timeline, role):
    state = timeline
    state["member"].role = role
    state["db"].commit()
    response = read(state, state["controls"]["mixed"].id)
    assert response.status_code == 200
    assert response.json() == simple_timeline(state, "mixed", [evidence_event(state, "early", 1)])


@pytest.mark.parametrize("limit", (0, 201))
def test_invalid_limit_does_not_read_or_mutate_timeline(timeline, limit):
    response = read(timeline, timeline["controls"]["own"].id, limit=limit)
    assert response.status_code == 422
    assert not any(
        "workspace_controls" in sql or "evidence_items" in sql for sql in timeline["statements"]
    )
