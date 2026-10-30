"""TC-06-002b: real citation routes and stored human/session authority.

SQLite controls run locally; the identical cases on migrated PostgreSQL provide
database qualification. No auth/service mocks or disabled database guards.
"""

import hashlib
import json
import secrets
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes.citation_composer import router
from app.core.database import get_db
from app.core.session import sign_session
from app.models import (
    ControlEvidenceLink,
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

MODELS = (
    User,
    Workspace,
    WorkspaceMember,
    UserSession,
    UserMfa,
    Framework,
    FrameworkControl,
    Document,
    WorkspaceControl,
    EvidenceItem,
    ControlEvidenceLink,
)
VERIFIED_AT = datetime(2026, 1, 2, 3, 4, 5)


def snapshot(db):
    """Compare every persisted column without printing session/password values."""
    return {
        model.__tablename__: hashlib.sha256(
            json.dumps(
                [
                    dict(row)
                    for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
                ],
                default=str,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def citations(request):
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
    token = secrets.token_hex(8)
    client = None

    def add(model, **values):
        row = model(**values)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        workspaces = []
        for name in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if db.get(Workspace, wid) is None:
                    break
            workspaces.append(add(Workspace, id=wid, name=name, slug=f"citations-{name}-{token}"))
        own, foreign = workspaces
        user = add(User, email=f"citations-{token}@example.com", password_hash="synthetic-unused")
        member = add(WorkspaceMember, user_id=user.id, workspace_id=own.id, role="reviewer")
        sid = f"citations-{token}"
        add(UserSession, user_id=user.id, session_id=sid)

        controls = {
            name: add(
                WorkspaceControl,
                workspace_id=foreign.id if name == "foreign" else own.id,
                custom_name=f"Synthetic {name} control",
                status="verified",
                last_reviewed_at=VERIFIED_AT,
                verified_at=VERIFIED_AT,
            )
            for name in ("mixed", "foreign_only", "valid", "foreign")
        }
        evidence = {
            name: add(
                EvidenceItem,
                workspace_id=foreign.id if name.startswith("foreign") else own.id,
                title=f"Synthetic {name} evidence",
                source_type="manual",
                source_metadata=json.dumps({"fixture": name}),
                approval_status="approved" if name.endswith("approved") else "pending",
            )
            for name in ("own_approved", "own_pending", "foreign_approved", "foreign_pending")
        }
        for control, item, confidence, verified in (
            ("mixed", "own_approved", 0.2, False),
            ("mixed", "own_pending", 0.35, False),
            ("mixed", "foreign_approved", 1.0, True),
            ("mixed", "foreign_pending", 0.99, True),
            ("foreign_only", "foreign_approved", 1.0, True),
            ("foreign_only", "foreign_pending", 0.99, True),
            ("valid", "own_approved", 0.9, True),
            ("valid", "own_pending", 0.35, False),
            ("foreign", "foreign_approved", 1.0, True),
        ):
            # All parent IDs exist. If migrated PostgreSQL rejects a cross-link,
            # fail and report that database protection; never bypass its guards.
            add(
                ControlEvidenceLink,
                control_id=controls[control].id,
                evidence_id=evidence[item].id,
                confidence_score=confidence,
                verified=verified,
                last_verified_at=VERIFIED_AT,
            )
        db.commit()
        missing_id = 2147483647
        assert db.get(WorkspaceControl, missing_id) is None
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        # Only connection ownership differs: the actual session validation,
        # current membership, route and citation service all execute unchanged.
        app.dependency_overrides[get_db] = database
        client = TestClient(app)
        client.cookies.set(
            "tc_session",
            sign_session(user.id, user.email, own.id, "reviewer", session_id=sid),
        )
        yield {
            "db": db,
            "client": client,
            "controls": {key: row.id for key, row in controls.items()},
            "evidence": {key: row.id for key, row in evidence.items()},
            "member": member,
            "missing": missing_id,
        }
    finally:
        if client is not None:
            client.close()
        db.rollback()
        # IDs were recorded only after successful INSERTs. Delete in FK order;
        # no global differences, truncation, sequence resets or trigger changes.
        for model in reversed(MODELS):
            if owned[model]:
                db.query(model).filter(model.id.in_(owned[model])).delete(synchronize_session=False)
        db.commit()
        assert snapshot(db) == before, "Cleanup changed pre-existing rows"
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def http(state, method, path, **kwargs):
    before = snapshot(state["db"])
    response = state["client"].request(method, path, **kwargs)
    state["db"].expire_all()
    assert snapshot(state["db"]) == before, "Citation read changed persisted rows"
    return response


def citation(state, name, confidence, verified):
    """Hand-specified public fields; no production serializer computes expectations."""
    return {
        "evidence_id": state["evidence"][name],
        "title": f"Synthetic {name} evidence",
        "source_type": "manual",
        "approval_status": "approved" if name == "own_approved" else "pending",
        "confidence_score": confidence,
        "verified": verified,
        "last_verified_at": "2026-01-02T03:04:05",
    }


def control(state, name):
    return {
        "control_id": state["controls"][name],
        "name": f"Synthetic {name} control",
        "description": None,
        "status": "verified",
        "last_reviewed_at": "2026-01-02T03:04:05",
        "verified_at": "2026-01-02T03:04:05",
    }


def test_mixed_links_cannot_project_foreign_metadata_or_inflate_strength(citations):
    state = citations
    response = http(state, "GET", f"/api/citations/control/{state['controls']['mixed']}")
    assert response.status_code == 200
    assert response.json() == {
        "control": control(state, "mixed"),
        "approved_evidence": [citation(state, "own_approved", 0.2, False)],
        "pending_evidence": [citation(state, "own_pending", 0.35, False)],
        "total_evidence": 2,
        "citation_strength": "weak",
    }


def test_foreign_only_links_produce_no_metadata_count_or_strength(citations):
    state = citations
    response = http(state, "GET", f"/api/citations/control/{state['controls']['foreign_only']}")
    assert response.status_code == 200
    assert response.json() == {
        "control": control(state, "foreign_only"),
        "approved_evidence": [],
        "pending_evidence": [],
        "total_evidence": 0,
        "citation_strength": "none",
    }


def test_same_workspace_citations_keep_approval_and_verification_fields(citations):
    state = citations
    response = http(state, "GET", f"/api/citations/control/{state['controls']['valid']}")
    assert response.status_code == 200
    assert response.json() == {
        "control": control(state, "valid"),
        "approved_evidence": [citation(state, "own_approved", 0.9, True)],
        "pending_evidence": [citation(state, "own_pending", 0.35, False)],
        "total_evidence": 2,
        "citation_strength": "strong",
    }


def test_mixed_answer_omits_foreign_controls_and_foreign_evidence(citations):
    state = citations
    response = http(
        state,
        "POST",
        "/api/citations/answer",
        json={
            "answer_text": "Synthetic answer. " * 20,
            "control_ids": [
                state["controls"][name] for name in ("mixed", "foreign", "valid", "foreign_only")
            ]
            + [state["missing"]],
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "answer_preview": ("Synthetic answer. " * 20)[:200],
        "controls_referenced": 3,
        "controls": [control(state, name) for name in ("mixed", "valid", "foreign_only")],
        "evidence_citations": [
            citation(state, "own_approved", 0.2, False),
            citation(state, "own_approved", 0.9, True),
        ],
        "citation_count": 2,
    }


def test_foreign_and_missing_controls_keep_existing_endpoint_semantics(citations):
    state = citations
    ids = [state["controls"]["foreign"], state["missing"]]
    for cid in ids:
        response = http(state, "GET", f"/api/citations/control/{cid}")
        assert response.status_code == 404
        assert response.json() == {"detail": "Control not found"}
    response = http(
        state,
        "POST",
        "/api/citations/answer",
        json={"answer_text": "Synthetic", "control_ids": ids},
    )
    assert response.status_code == 200
    assert response.json() == {
        "answer_preview": "Synthetic",
        "controls_referenced": 0,
        "controls": [],
        "evidence_citations": [],
        "citation_count": 0,
    }


@pytest.mark.parametrize(
    "authority,status", [("anonymous", 401), ("suspended", 403), ("removed", 403)]
)
def test_real_human_authority_is_required_for_both_endpoints(citations, authority, status):
    state = citations
    if authority == "anonymous":
        state["client"].cookies.clear()
    elif authority == "suspended":
        state["member"].suspended = True
        state["db"].commit()
    else:
        state["db"].delete(state["member"])
        state["db"].commit()
    cid = state["controls"]["valid"]
    read = http(state, "GET", f"/api/citations/control/{cid}")
    answer = http(
        state,
        "POST",
        "/api/citations/answer",
        json={"answer_text": "Synthetic", "control_ids": [cid]},
    )
    assert read.status_code == answer.status_code == status
    assert read.json() == answer.json()
    assert set(read.json()) == {"detail"}
