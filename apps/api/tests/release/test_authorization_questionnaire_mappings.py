"""TC-06-002c: authorize the questionnaire mapping PATCH before any mutation.

Real stored-session HTTP checks run as SQLite local controls and migrated
PostgreSQL acceptance. Collection does not connect to either database.
"""

import secrets
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.questionnaires import router
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    Document,
    Framework,
    FrameworkControl,
    Question,
    Questionnaire,
    QuestionMappingPreference,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
from app.models.tag import Tag

# Exact fixture-owned IDs are removed in FK-safe order, never by a watermark.
MODELS = (
    QuestionMappingPreference,
    Question,
    Questionnaire,
    Document,
    WorkspaceControl,
    FrameworkControl,
    Framework,
    Tag,
    AuditEvent,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
REFERENCE_NOT_FOUND = {"detail": "Referenced resource not found"}


def snapshot(db):
    db.expire_all()
    return {
        model.__tablename__: {
            row["id"]: dict(row)
            for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
        }
        for model in MODELS
    }


def assert_unchanged(db, before):
    # Check pending ORM state before expiring it: moving validation after a field
    # assignment must fail even if the HTTP error would later roll back the DB.
    assert not db.dirty and not db.new and not db.deleted, "Denied PATCH mutated ORM state"
    assert snapshot(db) == before, "Denied PATCH changed persisted full rows"


def assert_updated(db, before, mapping_id, changes, response):
    after = snapshot(db)
    expected = before["question_mapping_preferences"][mapping_id]
    actual = after["question_mapping_preferences"][mapping_id]
    assert actual["updated_at"] > expected["updated_at"]
    expected.update(changes, updated_at=actual["updated_at"])
    assert after == before, "PATCH changed fields/rows beyond the intended mapping update"
    assert response.json() == {
        key: actual[key]
        for key in (
            "id",
            "questionnaire_id",
            "question_id",
            "normalized_question_text",
            "preferred_control_id",
            "preferred_framework_key",
            "preferred_tag_id",
            "source",
            "confidence",
            "status",
            "approved",
        )
    } | {
        "created_at": actual["created_at"].isoformat(),
        "updated_at": actual["updated_at"].isoformat(),
    }


@pytest.fixture(
    params=(
        pytest.param("sqlite", marks=pytest.mark.unit),
        pytest.param("postgres", marks=pytest.mark.integration),
    )
)
def mapping_authority(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        from app.core.database import SessionLocal

        db = SessionLocal()
        engine = None
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        Base.metadata.create_all(engine, tables=[model.__table__ for model in MODELS])
        db = Session(engine)
    baseline = snapshot(db)
    owned = {model: [] for model in MODELS}

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        suffix = secrets.token_hex(8)
        first = db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM workspaces")).scalar_one()
        ws = add(Workspace, id=first, name="Mapping A", slug=f"mapping-a-{suffix}")
        other = add(Workspace, id=first + 1, name="Mapping B", slug=f"mapping-b-{suffix}")
        user = add(
            User,
            email=f"mapping-{suffix}@example.com",
            password_hash="synthetic-unused",
            email_verified=True,
        )
        member = add(WorkspaceMember, workspace_id=ws.id, user_id=user.id, role="admin")
        sid = secrets.token_hex(24)
        session_row = add(UserSession, user_id=user.id, session_id=sid)
        controls = {}
        tags = {}
        for name in ("initial", "own", "foreign"):
            target_ws = other.id if name == "foreign" else ws.id
            controls[name] = add(
                WorkspaceControl, workspace_id=target_ws, custom_name=f"{name} synthetic control"
            ).id
            tags[name] = add(
                Tag,
                workspace_id=target_ws,
                category="topic",
                key=f"{name}-{suffix}",
                label=f"{name} synthetic tag",
            ).id
        tags["global"] = add(
            Tag,
            workspace_id=None,
            category="topic",
            key=f"global-{suffix}",
            label="Global synthetic tag",
            is_system=True,
        ).id
        qnrs = {}
        mappings = {}
        for name in ("own", "untouched", "foreign"):
            target_ws = other.id if name == "foreign" else ws.id
            qnr = add(
                Questionnaire, workspace_id=target_ws, filename=f"{name}.xlsx", status="parsed"
            )
            question = add(Question, questionnaire_id=qnr.id, text=f"{name} synthetic question")
            ref = "foreign" if name == "foreign" else "initial"
            mapping = add(
                QuestionMappingPreference,
                workspace_id=target_ws,
                questionnaire_id=qnr.id,
                question_id=question.id,
                normalized_question_text=f"{name} normalized text",
                preferred_control_id=controls[ref],
                preferred_tag_id=tags[ref],
                preferred_framework_key="synthetic-initial",
                weight=1.5,
                source="ai",
                confidence=0.75,
                approved=False,
                status="suggested",
                created_by_user_id=user.id,
                created_at=datetime(2026, 1, 1),
                updated_at=datetime(2026, 1, 2),
            )
            qnrs[name] = qnr.id
            mappings[name] = mapping.id
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        # No authentication, membership, permission or reference lookup mocks.
        app.dependency_overrides[get_db] = lambda: db

        @contextmanager
        def client(role="admin"):
            if role is not None:
                member.role = role
                db.commit()
            with TestClient(app, raise_server_exceptions=False) as http:
                if role is not None:
                    http.cookies.set(
                        "tc_session",
                        sign_session(
                            user.id,
                            user.email,
                            workspace_id=ws.id,
                            role=role,
                            session_id=sid,
                            max_age_seconds=3600,
                        ),
                    )
                yield http

        yield {
            "db": db,
            "client": client,
            "qnrs": qnrs,
            "mappings": mappings,
            "controls": controls,
            "tags": tags,
            "other_ws": other.id,
            "member": member.id,
            "session": session_row.id,
            "path": f"/api/questionnaires/{qnrs['own']}/mappings/{mappings['own']}",
        }
    finally:
        try:
            db.rollback()
            for model in MODELS:
                if owned[model]:
                    db.query(model).filter(model.id.in_(owned[model])).delete(
                        synchronize_session=False
                    )
            db.commit()
            assert snapshot(db) == baseline, "Fixture did not restore every original full row"
        finally:
            db.close()
            if engine is not None:
                engine.dispose()


@pytest.mark.parametrize("role", ("admin", "editor"))
@pytest.mark.parametrize("tag", ("own", "global"))
def test_authorized_references_preserve_manual_override(mapping_authority, role, tag):
    f = mapping_authority
    body = {
        "preferred_control_id": f["controls"]["own"],
        "preferred_tag_id": f["tags"][tag],
        "preferred_framework_key": "synthetic-replacement",
    }
    with f["client"](role) as client:
        before = snapshot(f["db"])
        response = client.patch(f["path"], json=body)
    assert response.status_code == 200, response.text
    assert_updated(
        f["db"],
        before,
        f["mappings"]["own"],
        {**body, "status": "manual", "source": "manual", "approved": True},
        response,
    )


@pytest.mark.parametrize("role", ("admin", "editor"))
@pytest.mark.parametrize("status", ("suggested", "approved", "rejected", "manual"))
def test_explicit_status_and_source_behavior_is_preserved(mapping_authority, role, status):
    f = mapping_authority
    body = {"status": status, "preferred_control_id": f["controls"]["own"]}
    manual = status == "suggested"
    expected = {
        **body,
        "status": "manual" if manual else status,
        "source": "manual" if manual else "ai",
        "approved": manual or status in ("approved", "manual"),
    }
    with f["client"](role) as client:
        before = snapshot(f["db"])
        response = client.patch(f["path"], json=body)
    assert response.status_code == 200, response.text
    assert_updated(f["db"], before, f["mappings"]["own"], expected, response)


@pytest.mark.parametrize(
    "body,changes",
    (
        ({}, {}),
        (
            {
                "status": None,
                "preferred_control_id": None,
                "preferred_tag_id": None,
                "preferred_framework_key": None,
            },
            {},
        ),
        ({"preferred_tag_id": 0}, {"preferred_tag_id": None}),
        ({"preferred_framework_key": ""}, {"preferred_framework_key": None}),
        (
            {"preferred_control_id": 0},
            {
                "preferred_control_id": None,
                "status": "manual",
                "source": "manual",
                "approved": True,
            },
        ),
        (
            {"preferred_control_id": 0, "preferred_tag_id": 0, "preferred_framework_key": ""},
            {
                "preferred_control_id": None,
                "preferred_tag_id": None,
                "preferred_framework_key": None,
                "status": "manual",
                "source": "manual",
                "approved": True,
            },
        ),
    ),
)
def test_omitted_null_and_zero_clear_contract(mapping_authority, body, changes):
    f = mapping_authority
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch(f["path"], json=body)
    assert response.status_code == 200, response.text
    assert_updated(f["db"], before, f["mappings"]["own"], changes, response)


@pytest.mark.parametrize(
    "field,collection",
    (
        ("preferred_control_id", "controls"),
        ("preferred_tag_id", "tags"),
    ),
)
@pytest.mark.parametrize("target", ("foreign", "missing"))
def test_every_supplied_reference_is_validated_before_any_mutation(
    mapping_authority, field, collection, target
):
    f = mapping_authority
    body = {
        "status": "approved",
        "preferred_framework_key": "must-not-persist",
        "preferred_control_id": f["controls"]["own"],
        "preferred_tag_id": f["tags"]["global"],
    }
    body[field] = 2147483647 if target == "missing" else f[collection][target]
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch(f["path"], json=body)
        assert response.status_code == 404, response.text
        assert response.json() == REFERENCE_NOT_FOUND
        assert_unchanged(f["db"], before)


@pytest.mark.parametrize(
    "field,collection,model",
    (
        ("preferred_control_id", "controls", WorkspaceControl),
        ("preferred_tag_id", "tags", Tag),
    ),
)
def test_reference_uses_current_workspace(mapping_authority, field, collection, model):
    f = mapping_authority
    target = f[collection]["own"]
    f["db"].get(model, target).workspace_id = f["other_ws"]
    f["db"].commit()
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch(f["path"], json={field: target, "status": "manual"})
        assert response.status_code == 404, response.text
        assert response.json() == REFERENCE_NOT_FOUND
        assert_unchanged(f["db"], before)


@pytest.mark.parametrize("parent", ("archived", "moved", "removed", "missing", "foreign"))
def test_parent_must_be_current_and_available(mapping_authority, parent):
    f = mapping_authority
    qnr_id = f["qnrs"]["own"]
    row = f["db"].get(Questionnaire, qnr_id)
    if parent == "archived":
        row.deleted_at = datetime(2026, 1, 1)
    elif parent == "moved":
        row.workspace_id = f["other_ws"]
    elif parent == "removed":
        f["db"].delete(row)  # Existing FK cascade, never an orphan/constraint bypass.
    else:
        qnr_id = 2147483647 if parent == "missing" else f["qnrs"]["foreign"]
    f["db"].commit()
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch(
            f"/api/questionnaires/{qnr_id}/mappings/{f['mappings']['own']}",
            json={
                "status": "approved",
                "preferred_control_id": f["controls"]["own"],
                "preferred_tag_id": f["tags"]["global"],
                "preferred_framework_key": "not-saved",
            },
        )
        assert response.status_code == 404, response.text
        assert response.json() == REFERENCE_NOT_FOUND
        assert_unchanged(f["db"], before)


@pytest.mark.parametrize("target", ("foreign", "missing"))
def test_mapping_identity_is_still_scoped_to_parent_and_workspace(mapping_authority, target):
    f = mapping_authority
    mapping_id = 2147483647 if target == "missing" else f["mappings"]["foreign"]
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch(
            f"/api/questionnaires/{f['qnrs']['own']}/mappings/{mapping_id}",
            json={"status": "approved"},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Mapping not found"}
        assert_unchanged(f["db"], before)


@pytest.mark.parametrize("denial", ("anonymous", "reviewer", "revoked-session", "removed-member"))
def test_current_stored_authority_is_required(mapping_authority, denial):
    f = mapping_authority
    with f["client"](None if denial == "anonymous" else "admin") as client:
        # Mutate actual authority after signing the credential, not a dependency mock.
        if denial == "reviewer":
            f["db"].get(WorkspaceMember, f["member"]).role = "reviewer"
        elif denial == "revoked-session":
            f["db"].delete(f["db"].get(UserSession, f["session"]))
        elif denial == "removed-member":
            f["db"].delete(f["db"].get(WorkspaceMember, f["member"]))
        f["db"].commit()
        before = snapshot(f["db"])
        response = client.patch(f["path"], json={"status": "approved"})
        assert response.status_code == (401 if denial in ("anonymous", "revoked-session") else 403)
        assert_unchanged(f["db"], before)


@pytest.mark.parametrize("status", ("", "unknown"))
def test_invalid_status_preserves_existing_error_and_full_rows(mapping_authority, status):
    f = mapping_authority
    with f["client"]() as client:
        before = snapshot(f["db"])
        response = client.patch(
            f["path"],
            json={
                "status": status,
                "preferred_control_id": f["controls"]["own"],
                "preferred_tag_id": f["tags"]["global"],
            },
        )
        assert response.status_code == 400
        assert response.json() == {
            "detail": "Invalid status. Allowed: ['approved', 'manual', 'rejected', 'suggested']"
        }
        assert_unchanged(f["db"], before)
