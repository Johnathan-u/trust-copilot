"""TC-06-BUG-013: ids referenced by a request must belong to the caller's workspace.

Every endpoint below validates referenced ids with ``app.core.workspace_refs``. A missing id and an
id from another workspace both return the same 404 (never 200, 400, 403 or 500), and no row is
written. References inside the caller's own workspace keep working.

Two synthetic workspaces (1 and 2 from conftest); all data is synthetic and removed after each test.
"""

from collections.abc import Callable, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, WorkspaceMember
from app.models.ai_mapping import (
    ControlEvidenceMapping,
    EvidenceTagMapping,
    FrameworkControlMapping,
    QuestionMappingPreference,
)
from app.models.answer import Answer
from app.models.answer_delivery_outcome import AnswerDeliveryOutcome
from app.models.buyer_portal import BuyerEscalation, BuyerPortal, BuyerSatisfactionSignal
from app.models.control_evidence_link import ControlEvidenceLink
from app.models.deal import Deal
from app.models.evidence_item import EvidenceItem
from app.models.golden_answer import GoldenAnswer
from app.models.operator_queue import OperatorQueueItem
from app.models.proof_graph import AnswerReuseProvenance
from app.models.questionnaire import Question, Questionnaire
from app.models.remediation_audit import RemediationAuditEvent
from app.models.remediation_playbook import RemediationPlaybook, RemediationTicket
from app.models.tag import Tag
from app.models.trust_promise import TrustPromise
from app.models.workspace_control import WorkspaceControl

ADMIN_EMAIL = "admin-ref-scope@trust.local"
ADMIN_PASSWORD = "example-synthetic-test-admin-pw"
OTHER_EMAIL = "member-ref-scope-other@trust.local"
OWN_WS = 1
OTHER_WS = 2

# Tables an endpoint under test may write to; teardown removes rows created during the test.
WRITTEN = [
    ControlEvidenceLink,
    RemediationAuditEvent,
    AnswerDeliveryOutcome,
    AnswerReuseProvenance,
    BuyerSatisfactionSignal,
    BuyerEscalation,
    FrameworkControlMapping,
    ControlEvidenceMapping,
    EvidenceTagMapping,
    QuestionMappingPreference,
    OperatorQueueItem,
    TrustPromise,
    RemediationTicket,
]


def _max_id(db: Session, model) -> int:
    return db.query(func.max(model.id)).scalar() or 0


def _ensure_user(db: Session, email: str, password: str, ws: int) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, password_hash=hash_password(password), display_name=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    mem = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == ws)
        .first()
    )
    if not mem:
        db.add(WorkspaceMember(workspace_id=ws, user_id=user.id, role="admin"))
    else:
        mem.role = "admin"
    db.commit()
    return user


@pytest.fixture
def admin(client: TestClient, db_session: Session) -> TestClient:
    """Admin in workspace 1 only (not a member of workspace 2)."""
    _ensure_user(db_session, ADMIN_EMAIL, ADMIN_PASSWORD, OWN_WS)
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return client


def _make_ws_rows(db: Session, ws: int, tag: str) -> dict[str, Any]:
    qnr = Questionnaire(workspace_id=ws, filename=f"ref-scope-{tag}.xlsx", status="parsed")
    db.add(qnr)
    db.flush()
    qu = Question(questionnaire_id=qnr.id, text=f"Synthetic {tag} question?", section="S")
    db.add(qu)
    db.flush()
    ans = Answer(question_id=qu.id, text=f"Synthetic {tag} answer", status="draft")
    ctrl = WorkspaceControl(workspace_id=ws, custom_name=f"ref-scope-{tag}-control")
    rows = {
        "questionnaire": qnr,
        "question": qu,
        "answer": ans,
        "deal": Deal(workspace_id=ws, company_name=f"Ref Scope {tag} Co"),
        "golden_answer": GoldenAnswer(
            workspace_id=ws, question_text=f"ref scope {tag} q", answer_text="a"
        ),
        "control": ctrl,
        "evidence": EvidenceItem(workspace_id=ws, title=f"ref-scope-{tag}-evidence"),
        "tag": Tag(workspace_id=ws, category="topic", key=f"ref-scope-{tag}", label=tag),
        "playbook": RemediationPlaybook(
            workspace_id=ws, control_key=f"ref-scope-{tag}", title=f"PB {tag}"
        ),
        "promise": TrustPromise(
            workspace_id=ws, promise_text=f"{tag} promise", source_type="manual"
        ),
        "item": OperatorQueueItem(workspace_id=ws, title=f"ref-scope-{tag}-item"),
    }
    db.add_all([v for k, v in rows.items() if k not in ("questionnaire", "question")])
    db.flush()
    ticket = RemediationTicket(workspace_id=ws, title=f"ref-scope-{tag}-ticket", control_id=ctrl.id)
    db.add(ticket)
    db.flush()
    rows["ticket"] = ticket
    return rows


@pytest.fixture
def data(db_session: Session) -> Generator[dict[str, Any], None, None]:
    db = db_session
    start = {m: _max_id(db, m) for m in WRITTEN}
    own = _make_ws_rows(db, OWN_WS, "own")
    other = _make_ws_rows(db, OTHER_WS, "other-tenant")
    deleted_qnr = Questionnaire(
        workspace_id=OWN_WS,
        filename="ref-scope-own-deleted.xlsx",
        status="parsed",
        deleted_at=func.now(),
    )
    portal = BuyerPortal(
        workspace_id=OWN_WS, portal_token="ref-scope-tok-" + "x" * 24, display_name="P"
    )
    db.add_all([deleted_qnr, portal])
    db.commit()
    other_user = _ensure_user(db, OTHER_EMAIL, "synthetic-test-unused-pw", OTHER_WS)
    admin_user = _ensure_user(db, ADMIN_EMAIL, ADMIN_PASSWORD, OWN_WS)
    ids: dict[str, Any] = {f"own_{k}": v.id for k, v in own.items()}
    ids.update({f"other_{k}": v.id for k, v in other.items()})
    ids["own_user"] = admin_user.id
    ids["other_user"] = other_user.id
    ids["deleted_questionnaire"] = deleted_qnr.id
    ids["token"] = portal.portal_token
    portal_id = portal.id
    deleted_qnr_id, other_user_id = deleted_qnr.id, other_user.id
    cleanup = [
        (type(rows[key]), rows[key].id)
        for key in (
            "ticket",
            "item",
            "promise",
            "playbook",
            "tag",
            "evidence",
            "control",
            "golden_answer",
            "deal",
            "answer",
            "question",
            "questionnaire",
        )
        for rows in (own, other)
    ]
    model_for = {
        "questionnaire": Questionnaire,
        "question": Question,
        "answer": Answer,
        "deal": Deal,
        "golden_answer": GoldenAnswer,
        "control": WorkspaceControl,
        "evidence": EvidenceItem,
        "tag": Tag,
        "playbook": RemediationPlaybook,
        "promise": TrustPromise,
        "item": OperatorQueueItem,
        "ticket": RemediationTicket,
        "user": User,
    }
    for k, m in model_for.items():
        ids[f"missing_{k}"] = _max_id(db, m) + 100_000
    yield ids

    db.rollback()
    for m in WRITTEN:
        db.query(m).filter(m.id > start[m]).delete(synchronize_session=False)
    db.commit()
    for model, row_id in cleanup:
        db.query(model).filter(model.id == row_id).delete(synchronize_session=False)
    db.commit()
    db.query(BuyerPortal).filter(BuyerPortal.id == portal_id).delete(synchronize_session=False)
    db.query(Questionnaire).filter(Questionnaire.id == deleted_qnr_id).delete(
        synchronize_session=False
    )
    db.query(WorkspaceMember).filter(WorkspaceMember.user_id == other_user_id).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == other_user_id).delete(synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------
# Endpoint table: (name, method, path, body, written models) built from the data ids.
# ``ref`` is the id under test; every other reference is a valid own-workspace id.
# ---------------------------------------------------------------------------

Builder = Callable[[dict[str, Any], Any], tuple[str, str, dict | None]]


def _outcome(field: str) -> Builder:
    def build(d, ref):
        body = {"answer_id": d["own_answer"], "channel": "manual"}
        body[field] = ref
        return "POST", "/api/answer-outcomes", body

    return build


CASES: dict[str, tuple[str, Builder, list]] = {
    # name: (reference kind, request builder, models that must stay unchanged)
    "public-satisfaction.questionnaire_id": (
        "questionnaire",
        lambda d, ref: (
            "POST",
            f"/public/buyer-portal/{d['token']}/satisfaction",
            {"questionnaire_id": ref, "accepted_without_edits": True},
        ),
        [BuyerSatisfactionSignal],
    ),
    "public-escalation.answer_id": (
        "answer",
        lambda d, ref: (
            "POST",
            f"/public/buyer-portal/{d['token']}/escalations",
            {
                "buyer_email": "buyer@example.invalid",
                "escalation_type": "question",
                "message": "synthetic",
                "answer_id": ref,
            },
        ),
        [BuyerEscalation],
    ),
    "answer-outcomes.answer_id": ("answer", _outcome("answer_id"), [AnswerDeliveryOutcome]),
    "answer-outcomes.questionnaire_id": (
        "questionnaire",
        _outcome("questionnaire_id"),
        [AnswerDeliveryOutcome],
    ),
    "answer-outcomes.deal_id": ("deal", _outcome("deal_id"), [AnswerDeliveryOutcome]),
    "answer-outcomes.golden_answer_id": (
        "golden_answer",
        _outcome("golden_answer_id"),
        [AnswerDeliveryOutcome],
    ),
    "operator-queue.create.questionnaire_id": (
        "questionnaire",
        lambda d, ref: ("POST", "/api/operator-queue", {"title": "ref", "questionnaire_id": ref}),
        [OperatorQueueItem],
    ),
    "operator-queue.get": (
        "item",
        lambda d, ref: ("GET", f"/api/operator-queue/{ref}", None),
        [],
    ),
    "operator-queue.patch": (
        "item",
        lambda d, ref: ("PATCH", f"/api/operator-queue/{ref}", {"status": "in_progress"}),
        [],
    ),
    "operator-queue.delete": (
        "item",
        lambda d, ref: ("DELETE", f"/api/operator-queue/{ref}", None),
        [],
    ),
    "ai-mappings.framework-controls.control_id": (
        "control",
        lambda d, ref: (
            "POST",
            "/api/ai-mappings/framework-controls",
            {"framework_key": "REF-SCOPE", "control_id": ref},
        ),
        [FrameworkControlMapping],
    ),
    "ai-mappings.control-evidence.evidence_id": (
        "evidence",
        lambda d, ref: (
            "POST",
            "/api/ai-mappings/control-evidence",
            {"control_id": d["own_control"], "evidence_id": ref},
        ),
        [ControlEvidenceMapping],
    ),
    "ai-mappings.evidence-tags.tag_id": (
        "tag",
        lambda d, ref: (
            "POST",
            "/api/ai-mappings/evidence-tags",
            {"evidence_id": d["own_evidence"], "tag_id": ref},
        ),
        [EvidenceTagMapping],
    ),
    "ai-mappings.question-preferences.questionnaire_id": (
        "questionnaire",
        lambda d, ref: (
            "POST",
            "/api/ai-mappings/question-preferences",
            {"questionnaire_id": ref, "question_id": d["own_question"]},
        ),
        [QuestionMappingPreference],
    ),
    "ai-mappings.question-preferences.question_id": (
        "question",
        lambda d, ref: (
            "POST",
            "/api/ai-mappings/question-preferences",
            {"question_id": ref, "preferred_control_id": d["own_control"]},
        ),
        [QuestionMappingPreference],
    ),
    "proof-graph.reuse.answer_id": (
        "answer",
        lambda d, ref: ("POST", "/api/proof-graph/reuse-provenance", {"answer_id": ref}),
        [AnswerReuseProvenance],
    ),
    "proof-graph.reuse.deal_id": (
        "deal",
        lambda d, ref: (
            "POST",
            "/api/proof-graph/reuse-provenance",
            {"answer_id": d["own_answer"], "deal_id": ref},
        ),
        [AnswerReuseProvenance],
    ),
    "proof-graph.reuse.evidence_ids": (
        "evidence",
        lambda d, ref: (
            "POST",
            "/api/proof-graph/reuse-provenance",
            {"answer_id": d["own_answer"], "evidence_ids": [d["own_evidence"], ref]},
        ),
        [AnswerReuseProvenance],
    ),
    "promises.create.deal_id": (
        "deal",
        lambda d, ref: (
            "POST",
            "/api/promises",
            {"promise_text": "ref", "source_type": "manual", "deal_id": ref},
        ),
        [TrustPromise],
    ),
    "promises.create.owner_user_id": (
        "user",
        lambda d, ref: (
            "POST",
            "/api/promises",
            {"promise_text": "ref", "source_type": "manual", "owner_user_id": ref},
        ),
        [TrustPromise],
    ),
    "promises.create.control_ids": (
        "control",
        lambda d, ref: (
            "POST",
            "/api/promises",
            {"promise_text": "ref", "source_type": "manual", "control_ids": [ref]},
        ),
        [TrustPromise],
    ),
    "promises.get": ("promise", lambda d, ref: ("GET", f"/api/promises/{ref}", None), []),
    "promises.coverage": (
        "promise",
        lambda d, ref: ("GET", f"/api/promises/{ref}/coverage", None),
        [],
    ),
    "promises.map-controls.promise": (
        "promise",
        lambda d, ref: (
            "POST",
            f"/api/promises/{ref}/map-controls",
            {"control_ids": [d["own_control"]]},
        ),
        [],
    ),
    "promises.map-controls.control_ids": (
        "control",
        lambda d, ref: (
            "POST",
            f"/api/promises/{d['own_promise']}/map-controls",
            {"control_ids": [ref]},
        ),
        [],
    ),
    "remediation.create.control_id": (
        "control",
        lambda d, ref: ("POST", "/api/remediation/tickets", {"title": "ref", "control_id": ref}),
        [RemediationTicket],
    ),
    "remediation.create.playbook_id": (
        "playbook",
        lambda d, ref: ("POST", "/api/remediation/tickets", {"title": "ref", "playbook_id": ref}),
        [RemediationTicket],
    ),
    "remediation.create.assignee_user_id": (
        "user",
        lambda d, ref: (
            "POST",
            "/api/remediation/tickets",
            {"title": "ref", "assignee_user_id": ref},
        ),
        [RemediationTicket],
    ),
    "remediation.create.affected_deal_ids": (
        "deal",
        lambda d, ref: (
            "POST",
            "/api/remediation/tickets",
            {"title": "ref", "affected_deal_ids": [d["own_deal"], ref]},
        ),
        [RemediationTicket],
    ),
    "remediation.ticket.status": (
        "ticket",
        lambda d, ref: ("PATCH", f"/api/remediation/tickets/{ref}/status", {"status": "closed"}),
        [],
    ),
    "remediation.ticket.evidence.ticket": (
        "ticket",
        lambda d, ref: (
            "POST",
            f"/api/remediation/tickets/{ref}/evidence",
            {"evidence_ids": [d["own_evidence"]], "bump_control_to": None},
        ),
        [ControlEvidenceLink],
    ),
    "remediation.ticket.evidence.evidence_ids": (
        "evidence",
        lambda d, ref: (
            "POST",
            f"/api/remediation/tickets/{d['own_ticket']}/evidence",
            {"evidence_ids": [ref], "bump_control_to": None},
        ),
        [ControlEvidenceLink],
    ),
    "remediation.ticket.impact": (
        "ticket",
        lambda d, ref: ("GET", f"/api/remediation/tickets/{ref}/impact", None),
        [],
    ),
    "remediation.automation.ticket_id": (
        "ticket",
        lambda d, ref: (
            "POST",
            "/api/remediation/automations/mfa_re_enable/run",
            {"dry_run": True, "ticket_id": ref},
        ),
        [RemediationAuditEvent],
    ),
}


def _send(client: TestClient, method: str, path: str, body: dict | None):
    if body is None:
        return client.request(method, path)
    return client.request(method, path, json=body)


def _counts(db: Session, models: list) -> dict:
    db.expire_all()
    return {m.__tablename__: db.query(func.count(m.id)).scalar() for m in models}


def _snapshot(db: Session, d: dict[str, Any]) -> dict:
    """State of the other workspace's rows that path-id endpoints could modify."""
    db.expire_all()
    item = db.get(OperatorQueueItem, d["other_item"])
    ticket = db.get(RemediationTicket, d["other_ticket"])
    promise = db.get(TrustPromise, d["other_promise"])
    return {
        "item": (item.status if item else None),
        "ticket": (ticket.status if ticket else None, ticket.linked_evidence_ids_json),
        "promise": promise.control_ids_json if promise else None,
    }


@pytest.mark.parametrize("case", sorted(CASES))
def test_foreign_reference_is_404_like_missing(admin, db_session, data, case):
    kind, build, models = CASES[case]
    client = admin
    if case.startswith("public-"):
        client.cookies.clear()  # public token routes: no session
    before_counts = _counts(db_session, models)
    before_other = _snapshot(db_session, data)

    foreign = _send(client, *build(data, data[f"other_{kind}"]))
    missing = _send(client, *build(data, data[f"missing_{kind}"]))

    assert foreign.status_code == 404, foreign.text
    assert missing.status_code == 404, missing.text
    assert foreign.content == missing.content
    assert _counts(db_session, models) == before_counts
    assert _snapshot(db_session, data) == before_other


@pytest.mark.parametrize(
    "case",
    [
        "public-satisfaction.questionnaire_id",
        "answer-outcomes.questionnaire_id",
        "operator-queue.create.questionnaire_id",
        "ai-mappings.question-preferences.questionnaire_id",
    ],
)
def test_soft_deleted_questionnaire_is_404_like_missing(admin, db_session, data, case):
    _, build, models = CASES[case]
    if case.startswith("public-"):
        admin.cookies.clear()
    before = _counts(db_session, models)
    deleted = _send(admin, *build(data, data["deleted_questionnaire"]))
    missing = _send(admin, *build(data, data["missing_questionnaire"]))
    assert deleted.status_code == 404, deleted.text
    assert deleted.content == missing.content
    assert _counts(db_session, models) == before


@pytest.mark.parametrize("case", sorted(CASES))
def test_own_workspace_reference_still_works(admin, db_session, data, case):
    kind, build, _ = CASES[case]
    if case.startswith("public-"):
        admin.cookies.clear()
    r = _send(admin, *build(data, data[f"own_{kind}"]))
    assert r.status_code == 200, r.text


def test_global_tag_is_accepted(admin, db_session, data):
    tag = Tag(workspace_id=None, category="topic", key="ref-scope-global", label="global")
    db_session.add(tag)
    db_session.commit()
    try:
        r = admin.post(
            "/api/ai-mappings/evidence-tags",
            json={"evidence_id": data["own_evidence"], "tag_id": tag.id},
        )
        assert r.status_code == 200, r.text
    finally:
        db_session.rollback()
        db_session.query(EvidenceTagMapping).filter(EvidenceTagMapping.tag_id == tag.id).delete(
            synchronize_session=False
        )
        db_session.query(Tag).filter(Tag.id == tag.id).delete(synchronize_session=False)
        db_session.commit()
