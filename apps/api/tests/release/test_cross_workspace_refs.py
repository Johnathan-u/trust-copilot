"""TC-06-BUG-001: stored references must stay inside their own workspace.

1. Detection: synthetic cross-workspace rows are seeded and then deleted. Legacy parent rows
   are written while the parent-move migration is downgraded, not by disabling triggers.
   The read-only detector (app.services.cross_workspace_audit) reports every one of them.
2. Prevention (service layer): API writes that reference another workspace's document return 404
   (or 422 for a non-integer id), never 500, and write nothing.
3. Prevention (DB layer): migration tc06001_same_workspace_refs rejects new cross-workspace writes
   to evidence_items, export_records and evidence_gaps, leaves legacy rows writable on other
   columns, and upgrades cleanly while a legacy cross-workspace row exists.

Workspaces 1 and 2 come from conftest; every row here is synthetic and removed afterwards.
"""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import Document, User, WorkspaceMember
from app.models.answer import Answer
from app.models.answer_delivery_outcome import AnswerDeliveryOutcome
from app.models.ai_mapping import QuestionMappingPreference
from app.models.buyer_portal import BuyerEscalation, BuyerPortal, BuyerSatisfactionSignal
from app.models.chunk import Chunk
from app.models.control_evidence_link import ControlEvidenceLink
from app.models.deal import Deal
from app.models.evidence_gap import EvidenceGap
from app.models.evidence_item import EvidenceItem
from app.models.export_record import ExportRecord
from app.models.golden_answer import GoldenAnswer
from app.models.operator_queue import OperatorQueueItem
from app.models.proof_graph import AnswerReuseProvenance, ProofGraphEdge, ProofGraphNode
from app.models.questionnaire import Question, Questionnaire
from app.models.vendor_request import VendorRequest
from app.models.workspace_control import WorkspaceControl
from app.services.cross_workspace_audit import CHECKS, run_audit
from tests.release.test_parent_workspace_move import move_parent_before_triggers

OWN_WS = 1
OTHER_WS = 2
ADMIN_EMAIL = "admin-xws-refs@trust.local"
ADMIN_PASSWORD = "example-synthetic-test-xws-admin-pw"
API_ROOT = Path(__file__).resolve().parents[2]
TRIGGER_REVISION = "tc06001_same_workspace_refs"


@pytest.fixture(autouse=True)
def _workspaces(_ensure_test_data):
    """Conftest seeds workspaces 1 and 2 (and demo data) on first use."""


def _qnr_chain(db: Session, ws: int, tag: str) -> tuple[Questionnaire, Question, Answer]:
    qnr = Questionnaire(workspace_id=ws, filename=f"xws-{tag}.xlsx", status="parsed")
    db.add(qnr)
    db.flush()
    qu = Question(questionnaire_id=qnr.id, text=f"Synthetic {tag} question?", section="S")
    db.add(qu)
    db.flush()
    ans = Answer(question_id=qu.id, text=f"Synthetic {tag} answer", status="draft")
    db.add(ans)
    db.flush()
    return qnr, qu, ans


def _doc(db: Session, ws: int, tag: str) -> Document:
    d = Document(
        workspace_id=ws,
        storage_key=f"synthetic/xws-{tag}.pdf",
        filename=f"xws-{tag}.pdf",
        status="indexed",
    )
    db.add(d)
    db.flush()
    return d


def _counts(report: dict) -> dict[str, int]:
    return {c["check"]: c["count"] for c in report["checks"]}


def _ids(report: dict) -> dict[str, list[int]]:
    return {c["check"]: c.get("ids", []) for c in report["checks"]}


def _remember(cleanup: dict[str, list[int]], table: str, row_id: int) -> None:
    cleanup.setdefault(table, []).append(row_id)


def _delete_seed(db: Session, cleanup: dict[str, list[int]]) -> None:
    order = (
        "buyer_escalations",
        "buyer_satisfaction_signals",
        "proof_graph_edges",
        "answer_reuse_provenance",
        "question_mapping_preferences",
        "operator_queue_items",
        "answer_delivery_outcomes",
        "vendor_requests",
        "evidence_gaps",
        "export_records",
        "evidence_items",
        "deals",
        "answers",
        "questions",
        "questionnaires",
        "documents",
        "proof_graph_nodes",
        "buyer_portals",
        "golden_answers",
        "workspace_controls",
    )
    for table in order:
        ids = cleanup.get(table) or []
        if not ids:
            continue
        db.execute(
            text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        )
    db.commit()


def _seed_cross_workspace(db: Session) -> tuple[dict[str, int], dict[str, list[int]]]:
    """Seed one cross-workspace row per check. Returns check ids and rows to delete."""
    cleanup: dict[str, list[int]] = {}
    other_qnr, other_q, other_a = _qnr_chain(db, OTHER_WS, "other")
    other_deal = Deal(workspace_id=OTHER_WS, company_name="XWS Other Co")
    other_golden = GoldenAnswer(workspace_id=OTHER_WS, question_text="xws q", answer_text="a")
    other_ctrl = WorkspaceControl(workspace_id=OTHER_WS, custom_name="xws-other-control")
    other_ev = EvidenceItem(workspace_id=OTHER_WS, title="xws-other-evidence")
    other_node = ProofGraphNode(workspace_id=OTHER_WS, node_type="answer")
    other_portal = BuyerPortal(
        workspace_id=OTHER_WS,
        portal_token=f"xws-other-{uuid.uuid4().hex[:12]}",
        display_name="XWS",
    )
    db.add_all([other_deal, other_golden, other_ctrl, other_ev, other_node, other_portal])
    db.flush()
    _remember(cleanup, "questionnaires", other_qnr.id)
    _remember(cleanup, "questions", other_q.id)
    _remember(cleanup, "answers", other_a.id)
    _remember(cleanup, "deals", other_deal.id)
    _remember(cleanup, "golden_answers", other_golden.id)
    _remember(cleanup, "workspace_controls", other_ctrl.id)
    _remember(cleanup, "evidence_items", other_ev.id)
    _remember(cleanup, "proof_graph_nodes", other_node.id)
    _remember(cleanup, "buyer_portals", other_portal.id)

    # Trigger-protected tables: build valid rows, then move the parents to the other workspace.
    # This reproduces a legacy row without bypassing the new triggers.
    legacy_doc = _doc(db, OWN_WS, "legacy")
    legacy_qnr, legacy_q, legacy_a = _qnr_chain(db, OWN_WS, "legacy")
    ev = EvidenceItem(workspace_id=OWN_WS, title="xws-legacy-evidence", document_id=legacy_doc.id)
    exp = ExportRecord(
        workspace_id=OWN_WS,
        questionnaire_id=legacy_qnr.id,
        storage_key="synthetic/xws-export.xlsx",
        filename="xws-export.xlsx",
    )
    gap = EvidenceGap(
        workspace_id=OWN_WS,
        questionnaire_id=legacy_qnr.id,
        question_id=legacy_q.id,
        answer_id=legacy_a.id,
    )
    db.add_all([ev, exp, gap])
    db.flush()
    _remember(cleanup, "documents", legacy_doc.id)
    _remember(cleanup, "questionnaires", legacy_qnr.id)
    _remember(cleanup, "questions", legacy_q.id)
    _remember(cleanup, "answers", legacy_a.id)
    _remember(cleanup, "evidence_items", ev.id)
    _remember(cleanup, "export_records", exp.id)
    _remember(cleanup, "evidence_gaps", gap.id)
    held = {
        "other_qnr": other_qnr.id,
        "other_q": other_q.id,
        "other_a": other_a.id,
        "other_deal": other_deal.id,
        "other_golden": other_golden.id,
        "other_ctrl": other_ctrl.id,
        "other_ev": other_ev.id,
        "other_node": other_node.id,
        "other_portal": other_portal.id,
        "legacy_doc": legacy_doc.id,
        "legacy_qnr": legacy_qnr.id,
        "ev": ev.id,
        "exp": exp.id,
        "gap": gap.id,
    }
    # Parent-move triggers refuse this update. Seed it while that migration is downgraded.
    try:
        move_parent_before_triggers(db, "documents", held["legacy_doc"], OTHER_WS)
        move_parent_before_triggers(db, "questionnaires", held["legacy_qnr"], OTHER_WS)
    except Exception:
        db.rollback()
        _delete_seed(db, cleanup)
        raise

    vr = VendorRequest(
        workspace_id=OWN_WS,
        vendor_email="xws@example.invalid",
        questionnaire_id=held["other_qnr"],
    )
    ado = AnswerDeliveryOutcome(
        workspace_id=OWN_WS,
        answer_id=held["other_a"],
        questionnaire_id=held["other_qnr"],
        deal_id=held["other_deal"],
        golden_answer_id=held["other_golden"],
    )
    oq = OperatorQueueItem(
        workspace_id=OWN_WS, title="xws-item", questionnaire_id=held["other_qnr"]
    )
    pref = QuestionMappingPreference(
        workspace_id=OWN_WS,
        questionnaire_id=held["other_qnr"],
        question_id=held["other_q"],
        preferred_control_id=held["other_ctrl"],
    )
    reuse = AnswerReuseProvenance(
        workspace_id=OWN_WS,
        answer_id=held["other_a"],
        questionnaire_id=held["other_qnr"],
        deal_id=held["other_deal"],
        evidence_ids_json=json.dumps([held["other_ev"], "x", 99999999999]),
    )
    own_node = ProofGraphNode(workspace_id=OWN_WS, node_type="answer")
    db.add(own_node)
    db.flush()
    edge = ProofGraphEdge(
        workspace_id=OWN_WS,
        from_node_id=held["other_node"],
        to_node_id=held["other_node"],
        edge_type="xws",
    )
    sig = BuyerSatisfactionSignal(
        workspace_id=OWN_WS, portal_id=held["other_portal"], questionnaire_id=held["other_qnr"]
    )
    esc = BuyerEscalation(
        workspace_id=OWN_WS,
        portal_id=held["other_portal"],
        answer_id=held["other_a"],
        buyer_email="xws@example.invalid",
        escalation_type="question",
        message="synthetic",
    )
    deal = Deal(
        workspace_id=OWN_WS,
        company_name="XWS Own Co",
        linked_questionnaire_ids=json.dumps([held["other_qnr"]]),
    )
    malformed = Deal(
        workspace_id=OWN_WS, company_name="XWS Bad JSON", linked_questionnaire_ids="[1,"
    )
    db.add_all([vr, ado, oq, pref, reuse, edge, sig, esc, deal, malformed])
    db.flush()
    _remember(cleanup, "vendor_requests", vr.id)
    _remember(cleanup, "answer_delivery_outcomes", ado.id)
    _remember(cleanup, "operator_queue_items", oq.id)
    _remember(cleanup, "question_mapping_preferences", pref.id)
    _remember(cleanup, "answer_reuse_provenance", reuse.id)
    _remember(cleanup, "proof_graph_nodes", own_node.id)
    _remember(cleanup, "proof_graph_edges", edge.id)
    _remember(cleanup, "buyer_satisfaction_signals", sig.id)
    _remember(cleanup, "buyer_escalations", esc.id)
    _remember(cleanup, "deals", deal.id)
    _remember(cleanup, "deals", malformed.id)
    db.commit()
    checks = {
        "evidence_items.document_id": held["ev"],
        "export_records.questionnaire_id": held["exp"],
        "evidence_gaps.questionnaire_id": held["gap"],
        "evidence_gaps.question_id": held["gap"],
        "evidence_gaps.answer_id": held["gap"],
        "vendor_requests.questionnaire_id": vr.id,
        "answer_delivery_outcomes.answer_id": ado.id,
        "answer_delivery_outcomes.questionnaire_id": ado.id,
        "answer_delivery_outcomes.deal_id": ado.id,
        "answer_delivery_outcomes.golden_answer_id": ado.id,
        "operator_queue_items.questionnaire_id": oq.id,
        "question_mapping_preferences.questionnaire_id": pref.id,
        "question_mapping_preferences.question_id": pref.id,
        "question_mapping_preferences.preferred_control_id": pref.id,
        "answer_reuse_provenance.answer_id": reuse.id,
        "answer_reuse_provenance.questionnaire_id": reuse.id,
        "answer_reuse_provenance.deal_id": reuse.id,
        "answer_reuse_provenance.evidence_ids_json": reuse.id,
        "proof_graph_edges.from_node_id": edge.id,
        "proof_graph_edges.to_node_id": edge.id,
        "buyer_satisfaction_signals.portal_id": sig.id,
        "buyer_satisfaction_signals.questionnaire_id": sig.id,
        "buyer_escalations.portal_id": esc.id,
        "buyer_escalations.answer_id": esc.id,
        "deals.linked_questionnaire_ids": deal.id,
    }
    return checks, cleanup


# --- detection -----------------------------------------------------------------------------


def test_detector_covers_every_requested_reference():
    names = {c.name for c in CHECKS}
    for required in (
        "evidence_items.document_id",
        "export_records.questionnaire_id",
        "evidence_gaps.questionnaire_id",
        "evidence_gaps.question_id",
        "evidence_gaps.answer_id",
        "vendor_requests.questionnaire_id",
        "answer_delivery_outcomes.answer_id",
        "operator_queue_items.questionnaire_id",
        "question_mapping_preferences.question_id",
        "answer_reuse_provenance.answer_id",
        "buyer_satisfaction_signals.questionnaire_id",
        "deals.linked_questionnaire_ids",
    ):
        assert required in names
    report_only = [c.name for c in CHECKS if c.report_only]
    assert report_only == ["deals.linked_questionnaire_ids"]
    for c in CHECKS:
        assert c.sql.lstrip().upper().startswith(("SELECT", "WITH"))
        for verb in ("INSERT", "UPDATE ", "DELETE", "ALTER", "DROP", "TRUNCATE"):
            assert verb not in c.sql.upper()


def test_detector_finds_seeded_cross_workspace_rows(db_session: Session):
    cleanup: dict[str, list[int]] | None = None
    try:
        before = run_audit(db_session.connection(), read_only=False)
        seeded, cleanup = _seed_cross_workspace(db_session)
        after = run_audit(
            db_session.connection(), include_ids=True, id_limit=100000, read_only=False
        )
        b, a, ids = _counts(before), _counts(after), _ids(after)
        assert set(seeded) == set(a)
        for name, row_id in seeded.items():
            assert a[name] == b[name] + 1, name
            assert row_id in ids[name], name
        assert after["total"] == before["total"] + len(seeded)
        # Ids only: every entry has exactly these keys, ids are ints.
        for entry in after["checks"]:
            assert set(entry) <= {"check", "count", "ids", "report_only"}
            assert all(isinstance(i, int) for i in entry["ids"])
        assert "ids" not in before["checks"][0]
    finally:
        db_session.rollback()
        if cleanup:
            _delete_seed(db_session, cleanup)
    assert run_audit(db_session.connection(), read_only=False)["total"] == before["total"]
    db_session.rollback()


def test_detector_runs_in_read_only_transaction(db_session: Session):
    from app.core.database import engine

    with engine.connect() as conn:
        report = run_audit(conn)
        assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
        with pytest.raises(Exception):
            conn.execute(text("CREATE TEMP TABLE xws_should_fail (id int)"))
        conn.rollback()
    assert len(report["checks"]) == len(CHECKS)


def test_detector_script_print_sql_needs_no_database():
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    r = subprocess.run(
        [sys.executable, "scripts/detect_cross_workspace_refs.py", "--print-sql"],
        cwd=str(API_ROOT),
        env={**env, "TRUST_COPILOT_IN_DOCKER": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("SELECT COUNT(*)") == len(CHECKS)


# --- prevention: API -----------------------------------------------------------------------


def _ensure_admin(db: Session) -> None:
    user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if not user:
        user = User(
            email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD), display_name="x"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    mem = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == OWN_WS)
        .first()
    )
    if not mem:
        db.add(WorkspaceMember(workspace_id=OWN_WS, user_id=user.id, role="admin"))
    else:
        mem.role = "admin"
    db.commit()


@pytest.fixture
def api(client: TestClient, db_session: Session) -> Generator[tuple[TestClient, dict], None, None]:
    _ensure_admin(db_session)
    own_doc = _doc(db_session, OWN_WS, "api-own")
    other_doc = _doc(db_session, OTHER_WS, "api-other")
    ctrl = WorkspaceControl(workspace_id=OWN_WS, custom_name="xws-api-control")
    db_session.add(ctrl)
    db_session.flush()
    chunk = Chunk(workspace_id=OWN_WS, document_id=own_doc.id, text="synthetic xws chunk")
    db_session.add(chunk)
    db_session.commit()
    ids = {"own_doc": own_doc.id, "other_doc": other_doc.id, "control": ctrl.id, "chunk": chunk.id}
    ids["max_ev"] = db_session.query(func.max(EvidenceItem.id)).scalar() or 0
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    yield client, ids
    db_session.rollback()
    new_ev = EvidenceItem.id > ids["max_ev"]
    ev_ids = [i for (i,) in db_session.query(EvidenceItem.id).filter(new_ev).all()]
    db_session.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.evidence_id.in_(ev_ids)
    ).delete(synchronize_session=False)
    db_session.query(EvidenceItem).filter(new_ev).delete(synchronize_session=False)
    db_session.query(Chunk).filter(Chunk.id == ids["chunk"]).delete(synchronize_session=False)
    db_session.query(WorkspaceControl).filter(WorkspaceControl.id == ids["control"]).delete(
        synchronize_session=False
    )
    db_session.query(Document).filter(Document.id.in_([ids["own_doc"], ids["other_doc"]])).delete(
        synchronize_session=False
    )
    db_session.commit()


def _new_evidence(db: Session, ids: dict) -> int:
    db.rollback()
    return db.query(EvidenceItem).filter(EvidenceItem.id > ids["max_ev"]).count()


def _cases(ids: dict, doc_id) -> list[tuple[str, dict]]:
    return [
        ("/api/compliance/evidence", {"title": "xws", "document_id": doc_id}),
        (
            f"/api/compliance/controls/{ids['control']}/evidence/accept-suggested",
            {"chunk_id": ids["chunk"], "document_id": doc_id},
        ),
        ("/api/ingestion", {"source_type": "manual", "title": "xws", "document_id": doc_id}),
        (
            "/api/ingestion/batch",
            {
                "source_type": "manual",
                "items": [{"title": "ok"}, {"title": "x", "document_id": doc_id}],
            },
        ),
    ]


@pytest.mark.parametrize("which", ["other", "missing"])
@pytest.mark.parametrize("case", range(4))
def test_cross_workspace_document_write_is_404(api, db_session: Session, which: str, case: int):
    client, ids = api
    doc_id = ids["other_doc"] if which == "other" else 2_000_000_000
    path, body = _cases(ids, doc_id)[case]
    r = client.post(path, json=body)
    assert r.status_code == 404, (path, r.status_code)
    assert r.json()["detail"] == "Referenced resource not found"
    assert _new_evidence(db_session, ids) == 0


@pytest.mark.parametrize("case", range(4))
def test_same_workspace_document_write_still_works(api, db_session: Session, case: int):
    client, ids = api
    path, body = _cases(ids, ids["own_doc"])[case]
    r = client.post(path, json=body)
    assert r.status_code == 200, (path, r.status_code, r.text)
    db_session.rollback()
    docs = {
        d
        for (d,) in db_session.query(EvidenceItem.document_id)
        .filter(EvidenceItem.id > ids["max_ev"])
        .all()
    }
    assert ids["own_doc"] in docs
    assert docs <= {ids["own_doc"], None}


@pytest.mark.parametrize("bad", ["abc", "123", "own_doc_as_string"])
def test_batch_non_integer_document_id_is_422(api, db_session: Session, bad: str):
    """Only JSON integers are ids: a digit string is rejected, and the valid first item is not saved."""
    client, ids = api
    # The caller's own document id as a string would be written if digit strings were coerced.
    value = str(ids["own_doc"]) if bad == "own_doc_as_string" else bad
    r = client.post(
        "/api/ingestion/batch",
        json={
            "source_type": "manual",
            "items": [
                {"title": "ok", "document_id": ids["own_doc"]},
                {"title": "x", "document_id": value},
            ],
        },
    )
    assert r.status_code == 422, r.text
    assert _new_evidence(db_session, ids) == 0


# --- prevention: DB triggers ---------------------------------------------------------------


def _rejects(db: Session, row) -> None:
    db.add(row)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_db_rejects_cross_workspace_evidence_item(db_session: Session):
    other = _doc(db_session, OTHER_WS, "trg-ev")
    _rejects(db_session, EvidenceItem(workspace_id=OWN_WS, title="xws", document_id=other.id))


def test_db_rejects_cross_workspace_export_record(db_session: Session):
    qnr, _, _ = _qnr_chain(db_session, OTHER_WS, "trg-exp")
    _rejects(
        db_session,
        ExportRecord(
            workspace_id=OWN_WS, questionnaire_id=qnr.id, storage_key="synthetic/x", filename="x"
        ),
    )


@pytest.mark.parametrize("col", ["questionnaire_id", "question_id", "answer_id"])
def test_db_rejects_cross_workspace_evidence_gap(db_session: Session, col: str):
    qnr, qu, ans = _qnr_chain(db_session, OTHER_WS, f"trg-gap-{col}")
    value = {"questionnaire_id": qnr.id, "question_id": qu.id, "answer_id": ans.id}[col]
    _rejects(db_session, EvidenceGap(workspace_id=OWN_WS, **{col: value}))


def test_db_rejects_update_to_cross_workspace_reference(db_session: Session):
    own = _doc(db_session, OWN_WS, "trg-upd-own")
    other = _doc(db_session, OTHER_WS, "trg-upd-other")
    ev = EvidenceItem(workspace_id=OWN_WS, title="xws", document_id=own.id)
    db_session.add(ev)
    db_session.flush()
    ev.document_id = other.id
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_db_allows_same_workspace_null_and_set_null(db_session: Session):
    try:
        qnr, qu, ans = _qnr_chain(db_session, OWN_WS, "trg-ok")
        doc = _doc(db_session, OWN_WS, "trg-ok")
        ev = EvidenceItem(workspace_id=OWN_WS, title="xws-ok", document_id=doc.id)
        gap = EvidenceGap(
            workspace_id=OWN_WS, questionnaire_id=qnr.id, question_id=qu.id, answer_id=ans.id
        )
        bare = EvidenceGap(workspace_id=OWN_WS)
        exp = ExportRecord(
            workspace_id=OWN_WS, questionnaire_id=qnr.id, storage_key="synthetic/x", filename="x"
        )
        db_session.add_all([ev, gap, bare, exp])
        db_session.flush()
        db_session.execute(text("DELETE FROM documents WHERE id = :d"), {"d": doc.id})
        db_session.expire_all()
        assert db_session.get(EvidenceItem, ev.id).document_id is None
    finally:
        db_session.rollback()


def test_db_rejects_moving_row_to_other_workspace(db_session: Session):
    qnr, _, _ = _qnr_chain(db_session, OWN_WS, "trg-move")
    gap = EvidenceGap(workspace_id=OWN_WS, questionnaire_id=qnr.id)
    db_session.add(gap)
    db_session.flush()
    gap.workspace_id = OTHER_WS
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_db_allows_deleting_questionnaire_with_full_evidence_gap(db_session: Session):
    """Deleting a questionnaire must not trip the trigger while ON DELETE SET NULL clears its gaps."""
    try:
        qnr, qu, ans = _qnr_chain(db_session, OWN_WS, "trg-del-qnr")
        gap = EvidenceGap(
            workspace_id=OWN_WS, questionnaire_id=qnr.id, question_id=qu.id, answer_id=ans.id
        )
        db_session.add(gap)
        db_session.flush()
        db_session.execute(text("DELETE FROM questionnaires WHERE id = :q"), {"q": qnr.id})
        db_session.expire_all()
        row = db_session.get(EvidenceGap, gap.id)
        assert (row.questionnaire_id, row.question_id, row.answer_id) == (None, None, None)
    finally:
        db_session.rollback()


def test_legacy_cross_workspace_row_stays_writable_on_other_columns(db_session: Session):
    cleanup: dict[str, list[int]] | None = None
    try:
        seeded, cleanup = _seed_cross_workspace(db_session)
        ev = db_session.get(EvidenceItem, seeded["evidence_items.document_id"])
        ev.title = "xws-legacy-renamed"
        gap = db_session.get(EvidenceGap, seeded["evidence_gaps.answer_id"])
        gap.status = "resolved"
        db_session.flush()
        ev.document_id = None
        db_session.flush()
    finally:
        db_session.rollback()
        if cleanup:
            _delete_seed(db_session, cleanup)


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        # Fail fast instead of hanging if another connection holds a table lock.
        env={**os.environ, "TRUST_COPILOT_TESTING": "1", "PGOPTIONS": "-c lock_timeout=20000"},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_trigger_revision_is_on_the_single_alembic_head_chain():
    """One alembic head, and it is this revision or a descendant (no exact-parent pin)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert TRIGGER_REVISION in {r.revision for r in script.walk_revisions("base", heads[0])}


def test_trigger_migration_upgrades_with_legacy_rows_present(db_session: Session):
    """Downgrade/upgrade the trigger revision while a committed legacy cross-workspace row exists."""
    doc = _doc(db_session, OWN_WS, "mig-legacy")
    ev = EvidenceItem(workspace_id=OWN_WS, title="xws-mig-legacy", document_id=doc.id)
    db_session.add(ev)
    db_session.flush()
    ids = {"doc": doc.id, "ev": ev.id}
    move_parent_before_triggers(db_session, "documents", doc.id, OTHER_WS)
    db_session.commit()
    db_session.close()  # hold no locks while alembic swaps the triggers
    try:
        # A later revision may be the head. Step back to this revision so
        # downgrade -1 exercises the trigger migration itself.
        to_trigger = _alembic("downgrade", TRIGGER_REVISION)
        assert to_trigger.returncode == 0, to_trigger.stderr[-2000:]
        head = _alembic("current")
        assert TRIGGER_REVISION in head.stdout, head.stdout + head.stderr
        down = _alembic("downgrade", "-1")
        assert down.returncode == 0, down.stderr[-2000:]
        up = _alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr[-2000:]
        report = run_audit(db_session.connection(), include_ids=True, read_only=False)
        assert ids["ev"] in _ids(report)["evidence_items.document_id"]
        db_session.rollback()
    finally:
        _alembic("upgrade", "head")
        db_session.rollback()
        db_session.execute(text("DELETE FROM evidence_items WHERE id = :e"), {"e": ids["ev"]})
        db_session.execute(text("DELETE FROM documents WHERE id = :d"), {"d": ids["doc"]})
        db_session.commit()
