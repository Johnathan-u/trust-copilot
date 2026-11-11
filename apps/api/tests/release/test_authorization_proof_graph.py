"""TC-06-003f: live graph reads stay within current source/node authority.

Graphs are produced by the real sync API. Stored principals, FK enforcement,
ordinary source/node moves and cascading deletion are real on SQLite and PG.
Snapshot/history, stable IDs and authoritative artifact bytes are not redesigned.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import proof_graph
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    Answer,
    ApiKey,
    AuditEvent,
    CustomRole,
    Document,
    EvidenceItem,
    Framework,
    FrameworkControl,
    GoldenAnswer,
    Question,
    Questionnaire,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
from app.models.proof_graph import ProofGraphDiff, ProofGraphEdge, ProofGraphNode

MODELS = (
    ProofGraphEdge,
    ProofGraphNode,
    ProofGraphDiff,
    Answer,
    Question,
    Questionnaire,
    GoldenAnswer,
    WorkspaceControl,
    FrameworkControl,
    Framework,
    EvidenceItem,
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
KINDS = ("evidence_items", "golden_answers", "workspace_controls", "answers")
SOURCE_MODELS = {
    "evidence_items": EvidenceItem,
    "golden_answers": GoldenAnswer,
    "workspace_controls": WorkspaceControl,
    "answers": Answer,
}
DATE_FIELDS = {
    "evidence_items": "created_at",
    "golden_answers": "last_reviewed_at",
    "workspace_controls": "verified_at",
    "answers": "updated_at",
}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def snapshot(store):
    result = {}
    for model in MODELS:
        rows = [
            list(row) for row in store["db"].execute(select(model.__table__).order_by(model.id))
        ]
        result[model.__tablename__] = (
            len(rows),
            hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest(),
        )
    return result


@pytest.fixture(
    params=(
        pytest.param("sqlite", marks=pytest.mark.unit),
        pytest.param("postgres", marks=pytest.mark.integration),
    )
)
def graph_store(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        from app.core.database import SessionLocal

        db = SessionLocal()
        engine = db.get_bind()
        assert engine.dialect.name == "postgresql"
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        Base.metadata.create_all(engine, tables=[model.__table__ for model in MODELS])
        db = Session(engine)
    store = {"db": db, "engine": engine}
    original = snapshot(store)
    owned = {model: set() for model in MODELS}
    clients = []

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].add(row.id)
        return row

    def remember(current, _context):
        for row in current.new:
            if type(row) in owned:
                owned[type(row)].add(row.id)

    try:
        suffix = secrets.token_hex(8)
        first_ws = int(db.scalar(select(func.max(Workspace.id))) or 0) + 1
        ws = [
            add(Workspace, id=first_ws + i, name="Graph", slug=f"graph-{suffix}-{i}").id
            for i in range(2)
        ]
        users = [
            add(User, email=f"graph-{suffix}-{i}@example.com", password_hash="unused")
            for i in range(2)
        ]
        members = [
            add(WorkspaceMember, workspace_id=ws[i], user_id=users[i].id, role="admin")
            for i in range(2)
        ]
        add(
            CustomRole,
            workspace_id=ws[0],
            name="session_only",
            can_review=False,
            can_edit=False,
            can_admin=False,
            can_export=False,
        )
        sids = [secrets.token_hex(24) for _ in range(2)]
        sessions = [add(UserSession, user_id=users[i].id, session_id=sids[i]) for i in range(2)]
        evidence = add(
            EvidenceItem, workspace_id=ws[0], title="Synthetic evidence", approval_status="approved"
        )
        control = add(
            WorkspaceControl, workspace_id=ws[0], custom_name="Synthetic control", status="verified"
        )
        golden = add(
            GoldenAnswer,
            workspace_id=ws[0],
            question_text="Unique proof question",
            answer_text="Synthetic golden",
            evidence_ids_json=json.dumps([evidence.id]),
            control_ids_json=json.dumps([control.id]),
            status="approved",
        )
        qnrs, questions, answers = [], [], []
        for index in range(2):
            qnr = add(Questionnaire, workspace_id=ws[index], filename=f"graph-{index}.xlsx")
            question = add(
                Question,
                questionnaire_id=qnr.id,
                text="Unique proof question" if index == 0 else "Foreign question",
            )
            answer = add(
                Answer,
                question_id=question.id,
                text="Synthetic answer",
                status="approved",
                confidence=90,
            )
            qnrs.append(qnr.id)
            questions.append(question.id)
            answers.append(answer.id)
        db.commit()
        app = FastAPI()
        app.include_router(proof_graph.router, prefix="/api")

        def database():
            with Session(engine) as current:
                event.listen(current, "after_flush", remember)
                yield current

        app.dependency_overrides[get_db] = database
        for index in range(2):
            client = TestClient(app)
            clients.append(client)
            client.cookies.set(
                "tc_session",
                sign_session(
                    users[index].id,
                    users[index].email,
                    ws[index],
                    "admin",
                    session_id=sids[index],
                    max_age_seconds=3600,
                ),
            )
            response = client.post("/api/proof-graph/sync")
            assert response.status_code == 200
            assert response.json() == (
                {"nodes": 4, "edges": 3} if index == 0 else {"nodes": 1, "edges": 0}
            )
        nodes = {
            row.ref_table: row.id
            for row in db.scalars(
                select(ProofGraphNode).where(ProofGraphNode.workspace_id == ws[0])
            )
        }
        assert set(nodes) == set(KINDS)
        foreign_node = db.scalar(
            select(ProofGraphNode.id).where(ProofGraphNode.workspace_id == ws[1])
        )
        store.update(
            client=clients[0],
            ws=ws,
            member=members[0],
            session=sessions[0],
            nodes=nodes,
            foreign_node=foreign_node,
            qnrs=qnrs,
            questions=questions,
            answers=answers,
            add=add,
            sources={
                "evidence_items": evidence.id,
                "golden_answers": golden.id,
                "workspace_controls": control.id,
                "answers": answers[0],
            },
        )
        yield store
    finally:
        for client in clients:
            client.close()
        db.rollback()
        try:
            for model in MODELS:
                if owned[model]:
                    db.query(model).filter(model.id.in_(owned[model])).delete(
                        synchronize_session=False
                    )
            db.commit()
            assert snapshot(store) == original
        finally:
            db.close()
            if request.param == "sqlite":
                engine.dispose()


def read(store, path, status=200, detail=None):
    before = snapshot(store)
    writes = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(store["engine"], "before_cursor_execute", capture)
    try:
        response = store["client"].get(path)
    finally:
        event.remove(store["engine"], "before_cursor_execute", capture)
    assert response.status_code == status
    if detail is not None:
        assert response.json() == {"detail": detail}
    assert not writes, "Graph reads must not write SQL, even if subsequently rolled back"
    assert snapshot(store) == before
    return response.json()


def freshness_path(store, kind):
    return f'/api/proof-graph/freshness/node/{store["nodes"][kind]}'


def chain_path(store, answer_id=None):
    return (
        f'/api/proof-graph/chain/answer/{store["answers"][0] if answer_id is None else answer_id}'
    )


def source(store, kind):
    return store["db"].get(SOURCE_MODELS[kind], store["sources"][kind])


def move_source(store, kind, hours):
    row = source(store, kind)
    if kind == "answers":
        store["db"].get(Questionnaire, store["qnrs"][0]).workspace_id = store["ws"][1]
    else:
        row.workspace_id = store["ws"][1]
    setattr(row, DATE_FIELDS[kind], now() - timedelta(hours=hours))
    store["db"].commit()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "hours,expected", [(1, "live"), (24, "recent"), (168, "aging"), (960, "stale")]
)
def test_owned_source_age_buckets_remain_unchanged(graph_store, kind, hours, expected):
    s = graph_store
    setattr(source(s, kind), DATE_FIELDS[kind], now() - timedelta(hours=hours))
    s["db"].commit()
    assert read(s, freshness_path(s, kind)) == {"node_id": s["nodes"][kind], "freshness": expected}


@pytest.mark.parametrize("expired", [False, True])
def test_owned_golden_expiry_still_overrides_recent_review(graph_store, expired):
    s = graph_store
    row = source(s, "golden_answers")
    row.last_reviewed_at = now()
    row.expires_at = now() + timedelta(days=-1 if expired else 1)
    s["db"].commit()
    assert read(s, freshness_path(s, "golden_answers"))["freshness"] == (
        "stale" if expired else "live"
    )


def test_own_archived_answer_freshness_preserves_its_existing_age_bucket(graph_store):
    s = graph_store
    s["db"].get(Questionnaire, s["qnrs"][0]).deleted_at = now()
    source(s, "answers").updated_at = now()
    s["db"].commit()
    assert read(s, freshness_path(s, "answers"))["freshness"] == "live"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("hours", [1, 2400])
def test_freshness_does_not_read_current_foreign_source_dates(graph_store, kind, hours):
    s = graph_store
    move_source(s, kind, hours)
    expected = "aging" if kind == "answers" else "stale"
    assert read(s, freshness_path(s, kind)) == {"node_id": s["nodes"][kind], "freshness": expected}


@pytest.mark.parametrize("kind", KINDS[:-1])
@pytest.mark.parametrize("hours", [1, 2400])
def test_chain_keeps_cached_own_fields_without_reading_foreign_source_dates(
    graph_store, kind, hours
):
    s = graph_store
    before = read(s, chain_path(s))
    move_source(s, kind, hours)
    after = read(s, chain_path(s))
    assert after["answer_id"] == before["answer_id"]
    assert len(after["chain"]) == 4
    assert [{k: v for k, v in n.items() if k != "freshness"} for n in after["chain"]] == [
        {k: v for k, v in n.items() if k != "freshness"} for n in before["chain"]
    ]
    assert next(n for n in after["chain"] if n["id"] == s["nodes"][kind])["freshness"] == "stale"


@pytest.mark.parametrize("kind", KINDS)
def test_deleted_sources_keep_existing_freshness_fallbacks(graph_store, kind):
    s = graph_store
    if kind == "answers":
        s["db"].delete(s["db"].get(Questionnaire, s["qnrs"][0]))
    else:
        s["db"].delete(source(s, kind))
    s["db"].commit()
    s["db"].expire_all()
    assert source(s, kind) is None
    expected = "aging" if kind == "answers" else "stale"
    assert read(s, freshness_path(s, kind))["freshness"] == expected


@pytest.mark.parametrize("state", ["foreign", "moved", "missing"])
def test_unavailable_graph_node_retains_route_404(graph_store, state):
    s = graph_store
    node_id = s["foreign_node"] if state == "foreign" else s["nodes"]["golden_answers"]
    if state == "moved":
        s["db"].get(ProofGraphNode, node_id).workspace_id = s["ws"][1]
        s["db"].commit()
    elif state == "missing":
        node_id = int(s["db"].scalar(select(func.max(ProofGraphNode.id)))) + 100_000
    read(s, f"/api/proof-graph/freshness/node/{node_id}", 404, "Node not found")


@pytest.mark.parametrize(
    "state",
    [
        "archived",
        "moved",
        "foreign",
        "deleted_parent",
        "deleted_question",
        "deleted_answer",
        "missing",
        "moved_root_node",
        "uncached",
    ],
)
def test_chain_requires_current_active_answer_parent_and_cached_owned_node(graph_store, state):
    s = graph_store
    answer_id = s["answers"][0]
    if state == "archived":
        s["db"].get(Questionnaire, s["qnrs"][0]).deleted_at = now()
    elif state == "moved":
        s["db"].get(Questionnaire, s["qnrs"][0]).workspace_id = s["ws"][1]
    elif state == "foreign":
        answer_id = s["answers"][1]
    elif state.startswith("deleted_"):
        model, row_id = {
            "deleted_parent": (Questionnaire, s["qnrs"][0]),
            "deleted_question": (Question, s["questions"][0]),
            "deleted_answer": (Answer, answer_id),
        }[state]
        s["db"].delete(s["db"].get(model, row_id))
    elif state == "missing":
        answer_id = int(s["db"].scalar(select(func.max(Answer.id)))) + 100_000
    elif state == "moved_root_node":
        s["db"].get(ProofGraphNode, s["nodes"]["answers"]).workspace_id = s["ws"][1]
    else:
        question = s["add"](Question, questionnaire_id=s["qnrs"][0], text="New uncached question")
        answer_id = s["add"](Answer, question_id=question.id, text="Uncached answer").id
    s["db"].commit()
    if state.startswith("deleted_"):
        s["db"].expire_all()
        assert s["db"].get(Answer, answer_id) is None
    read(s, chain_path(s, answer_id), 404, "Answer not in proof graph")


@pytest.mark.parametrize("kind", KINDS[:-1])
def test_chain_never_traverses_a_current_foreign_graph_node(graph_store, kind):
    s = graph_store
    node = s["db"].get(ProofGraphNode, s["nodes"][kind])
    node.workspace_id = s["ws"][1]
    node.label = "New foreign private label"
    node.meta_json = '{"private":"new foreign metadata"}'
    s["db"].commit()
    result = read(s, chain_path(s))
    visible = {item["id"] for item in result["chain"]}
    expected = (
        {s["nodes"]["answers"]}
        if kind == "golden_answers"
        else set(s["nodes"].values()) - {node.id}
    )
    assert visible == expected
    assert "New foreign private label" not in json.dumps(result)
    assert "new foreign metadata" not in json.dumps(result)


@pytest.mark.parametrize("route", ["freshness", "chain"])
@pytest.mark.parametrize("role", ["admin", "editor", "reviewer", "session_only"])
def test_graph_reads_preserve_current_session_only_permission(graph_store, route, role):
    s = graph_store
    s["member"].role = role
    s["db"].commit()
    read(s, freshness_path(s, "golden_answers") if route == "freshness" else chain_path(s))


@pytest.mark.parametrize("route", ["freshness", "chain"])
@pytest.mark.parametrize(
    "revocation", ["suspended", "membership_removed", "session_removed", "anonymous"]
)
def test_graph_reads_reject_current_authority_loss(graph_store, route, revocation):
    s = graph_store
    if revocation == "suspended":
        s["member"].suspended = True
    elif revocation == "anonymous":
        s["client"].cookies.clear()
    else:
        s["db"].delete(s["session"] if revocation == "session_removed" else s["member"])
    s["db"].commit()
    status = 401 if revocation in ("session_removed", "anonymous") else 403
    read(s, freshness_path(s, "golden_answers") if route == "freshness" else chain_path(s), status)


def test_owned_synced_chain_preserves_complete_output_fields(graph_store):
    s = graph_store
    result = read(s, chain_path(s))
    assert result["answer_id"] == s["answers"][0]
    assert {n["id"] for n in result["chain"]} == set(s["nodes"].values())
    assert len(result["chain"]) == 4
    expected = {
        "evidence_items": (
            "evidence",
            "Synthetic evidence",
            {"approval_status": "approved", "source_type": "manual"},
        ),
        "workspace_controls": ("control", "Synthetic control", {"status": "verified"}),
        "golden_answers": (
            "golden_answer",
            "Unique proof question",
            {"status": "approved", "confidence": None},
        ),
        "answers": (
            "answer",
            "Unique proof question",
            {"status": "approved", "confidence": 90, "questionnaire_id": s["qnrs"][0]},
        ),
    }
    for item in result["chain"]:
        kind = item["ref_table"]
        node_type, label, meta = expected[kind]
        assert set(item) == {
            "id",
            "node_type",
            "ref_table",
            "ref_id",
            "label",
            "meta_json",
            "version",
            "freshness",
        }
        assert item["node_type"] == node_type and item["ref_id"] == s["sources"][kind]
        assert item["label"] == label and json.loads(item["meta_json"]) == meta
        assert item["version"] == 1 and item["freshness"] == "live"
