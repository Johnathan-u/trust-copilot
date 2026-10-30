"""TC-06-002a: export-pack object boundaries, not full core authorization.

Real routers, stored members/sessions and authentication run against both SQLite
local controls and migrated PostgreSQL acceptance. Collection opens no database.
"""

import json
import secrets
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.export_pack import router
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    Answer,
    ApiKey,
    AuditEvent,
    CustomRole,
    Document,
    Question,
    Questionnaire,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.models.evidence_gap import EvidenceGap

# FK-safe cleanup order. Delete only the exact IDs this fixture inserts.
MODELS = (
    EvidenceGap,
    Answer,
    Question,
    Questionnaire,
    Document,
    AuditEvent,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
ENDPOINTS = ("", "/cover", "/summary", "/evidence")


def snapshot(db):
    return {
        model.__tablename__: [
            tuple(row) for row in db.execute(select(model.__table__).order_by(model.id))
        ]
        for model in MODELS
    }


@pytest.fixture(
    params=(
        pytest.param("sqlite", marks=pytest.mark.unit),
        pytest.param("postgres", marks=pytest.mark.integration),
    )
)
def export_authority(request):
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
    before = snapshot(db)
    owned = {model: [] for model in MODELS}

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        suffix = secrets.token_hex(8)
        # Shared seed data uses explicit workspace IDs; allocate above existing
        # rows without altering a sequence or any pre-existing record.
        first = db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM workspaces")).scalar_one()
        ws = add(Workspace, id=first, name="Export A", slug=f"export-a-{suffix}")
        other = add(Workspace, id=first + 1, name="Export B", slug=f"export-b-{suffix}")
        user = add(
            User,
            email=f"export-{suffix}@example.com",
            password_hash="synthetic-unused",
            email_verified=True,
        )
        member = add(WorkspaceMember, workspace_id=ws.id, user_id=user.id, role="admin")
        sid = secrets.token_hex(24)
        add(UserSession, user_id=user.id, session_id=sid)
        docs = [
            add(
                Document,
                workspace_id=ws.id,
                filename="Own policy.pdf",
                storage_key=f"synthetic/{suffix}/a",
            ),
            add(
                Document,
                workspace_id=ws.id,
                filename="Own archived.pdf",
                storage_key=f"synthetic/{suffix}/b",
                deleted_at=datetime(2026, 1, 1),
            ),
            add(
                Document,
                workspace_id=other.id,
                filename="FOREIGN private.pdf",
                storage_key=f"synthetic/{suffix}/foreign",
            ),
        ]
        own = add(
            Questionnaire, workspace_id=ws.id, filename="Own questionnaire.xlsx", status="parsed"
        )
        foreign = add(
            Questionnaire,
            workspace_id=other.id,
            filename="FOREIGN questionnaire.xlsx",
            status="parsed",
        )
        question = add(
            Question, questionnaire_id=own.id, text="Synthetic own question", section="Own section"
        )
        foreign_question = add(
            Question,
            questionnaire_id=foreign.id,
            text="FOREIGN question",
            section="FOREIGN section",
        )
        answer = add(
            Answer,
            question_id=question.id,
            text="Own answer",
            confidence=95,
            citations=json.dumps(
                [
                    {"document_id": docs[0].id, "text": "Own citation"},
                    {"document_id": docs[0].id, "text": "Repeated own citation"},
                    {"document_id": docs[1].id, "text": "Archived but still owned"},
                ]
            ),
        )
        add(
            Answer,
            question_id=foreign_question.id,
            text="FOREIGN answer",
            citations=json.dumps([{"document_id": docs[2].id, "text": "FOREIGN citation"}]),
        )
        add(
            EvidenceGap,
            workspace_id=ws.id,
            questionnaire_id=own.id,
            reason="Own open gap",
            status="open",
        )
        add(
            EvidenceGap,
            workspace_id=ws.id,
            questionnaire_id=own.id,
            reason="Own resolved gap",
            status="resolved",
        )
        add(
            EvidenceGap,
            workspace_id=other.id,
            questionnaire_id=foreign.id,
            reason="FOREIGN gap",
            status="open",
        )
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        # Only the database is injected: signing, session lookup, membership and
        # the production route/service are real. No provider/storage call occurs.
        app.dependency_overrides[get_db] = lambda: db

        @contextmanager
        def client(role="admin"):
            if role is not None:
                member.role = role
                db.commit()
            with TestClient(app) as http:
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

        def get(http, endpoint, qnr_id):
            prior = snapshot(db)
            response = http.get(f"/api/export-pack{endpoint}", params={"questionnaire_id": qnr_id})
            db.expire_all()
            assert snapshot(db) == prior, "Export GET changed persisted full rows"
            return response

        yield {
            "db": db,
            "client": client,
            "get": get,
            "own": own.id,
            "foreign": foreign.id,
            "ws": ws.id,
            "other_ws": other.id,
            "docs": [d.id for d in docs],
            "answer": answer.id,
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
            assert snapshot(db) == before, "Fixture must restore every original full row and count"
        finally:
            db.close()
            if engine is not None:
                engine.dispose()


def bundle(payload, endpoint):
    return payload["evidence_bundle"] if endpoint == "" else payload


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("role", ("admin", "editor", "reviewer"))
def test_authorized_export_pack_preserves_existing_outputs(export_authority, endpoint, role):
    f = export_authority
    with f["client"](role) as client:
        response = f["get"](client, endpoint, f["own"])
    assert response.status_code == 200, response.text
    data = response.json()
    assert "FOREIGN" not in response.text
    if endpoint in ("", "/evidence"):
        evidence = bundle(data, endpoint)
        assert evidence["total_documents_cited"] == 2
        assert evidence["total_citations"] == 3
        assert {d["id"] for d in evidence["documents"]} == set(f["docs"][:2])
        assert {d["filename"] for d in evidence["documents"]} == {
            "Own policy.pdf",
            "Own archived.pdf",
        }
        assert all(d["upload_date"] for d in evidence["documents"])
        assert len(evidence["evidence_gaps"]) == 1
        assert evidence["evidence_gaps_resolved"] == 1
    if endpoint in ("", "/cover"):
        cover = data["cover_page"] if endpoint == "" else data
        assert cover["questionnaire_title"] == "Own questionnaire.xlsx"
        assert cover["total_questions"] == cover["total_answers"] == 1
        assert cover["completion_pct"] == 100
    if endpoint in ("", "/summary"):
        summary = data["executive_summary"] if endpoint == "" else data
        assert summary["total_questions"] == summary["total_answers"] == 1
        assert summary["completion_rate"] == 100
        assert summary["average_confidence"] == 95


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_foreign_and_missing_questionnaire_are_indistinguishable(export_authority, endpoint):
    f = export_authority
    with f["client"]() as client:
        foreign = f["get"](client, endpoint, f["foreign"])
        missing = f["get"](client, endpoint, 2147483647)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Questionnaire not found"}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unauthenticated_export_pack_does_not_disclose_objects(export_authority, endpoint):
    f = export_authority
    with f["client"](None) as client:
        response = f["get"](client, endpoint, f["foreign"])
    assert response.status_code == 401
    assert "FOREIGN" not in response.text


@pytest.mark.parametrize("endpoint", ("", "/evidence"))
def test_mixed_and_unknown_citations_count_only_authorized_documents(export_authority, endpoint):
    f = export_authority
    row = f["db"].get(Answer, f["answer"])
    row.citations = json.dumps(
        [
            {"document_id": []},
            "not a citation",
            {"document_id": f["docs"][0]},
            {"document_id": f["docs"][2]},
            {"document_id": 2147483647},
            {"document_id": f["docs"][0]},
        ]
    )
    f["db"].commit()
    with f["client"]() as client:
        response = f["get"](client, endpoint, f["own"])
    assert response.status_code == 200
    evidence = bundle(response.json(), endpoint)
    assert evidence["total_citations"] == 2
    assert evidence["total_documents_cited"] == 1
    assert [d["id"] for d in evidence["documents"]] == [f["docs"][0]]
    assert "FOREIGN" not in response.text


@pytest.mark.parametrize(
    "raw",
    (
        "broken-json",
        "{}",
        "null",
        '[{}, {"chunk_id": 1}, {"document_id": null}]',
        '[{"document_id": true}, {"document_id": "1"}, {"document_id": 1.0}, {"document_id": []}, {"document_id": -1}, {"document_id": 2147483648}]',
    ),
)
def test_unresolved_or_malformed_references_never_count_as_authorized(export_authority, raw):
    f = export_authority
    f["db"].get(Answer, f["answer"]).citations = raw
    f["db"].commit()
    with f["client"]() as client:
        response = f["get"](client, "/evidence", f["own"])
    assert response.status_code == 200
    assert response.json()["total_documents_cited"] == 0
    assert response.json()["total_citations"] == 0
    assert response.json()["documents"] == []


@pytest.mark.parametrize("endpoint", ("", "/evidence"))
def test_document_reference_uses_current_workspace(export_authority, endpoint):
    f = export_authority
    f["db"].get(Document, f["docs"][0]).workspace_id = f["other_ws"]
    f["db"].commit()
    with f["client"]() as client:
        response = f["get"](client, endpoint, f["own"])
    assert response.status_code == 200
    evidence = bundle(response.json(), endpoint)
    assert evidence["total_citations"] == evidence["total_documents_cited"] == 1
    assert [d["id"] for d in evidence["documents"]] == [f["docs"][1]]
