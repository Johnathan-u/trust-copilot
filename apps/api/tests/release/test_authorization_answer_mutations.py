"""TC-06-002g: individual writes require a current, available answer parent.

Reuse the reviewed TC-12-001 stored-auth/FK fixture without altering its routes,
bulk assertions or cleanup. All cases execute against SQLite and migrated PG;
missing chains are represented by ordinary cascading deletion, never FK bypass.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select

from app.models import Answer, Question, Questionnaire, UserSession, WorkspaceMember
from tests.release import test_answer_routing as routing

answers_authority = routing.answers_authority
assert_answer_changes = routing.assert_answer_changes
snapshot = routing.snapshot

ACTIONS = ("create", "create-slash", "upsert", "upsert-slash", "patch")


def target_ids(store, action, name=None):
    name = name or ("new" if action.startswith("create") else "existing")
    return store["questions"][name], store["answers"].get(name)


def send(client, action, qid, aid, body=None):
    body = {"text": "Human replacement", "status": "approved"} if body is None else body
    if action == "patch":
        return client.patch(f"/api/answers/{aid}", json=body)
    suffix = "/" if action.endswith("-slash") else ""
    return client.post(f"/api/answers{suffix}", json={"question_id": qid, **body})


def denied(store, client, action, qid, aid, status, detail=None):
    db = store["db"]
    before = snapshot(db)
    writes = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        response = send(client, action, qid, aid)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert response.status_code == status
    assert not response.history and "location" not in response.headers
    if detail is not None:
        assert response.json() == {"detail": detail}
    assert not writes, "Parent authorization must precede SQL writes, even before rollback"
    assert not db.new and not db.dirty and not db.deleted
    assert snapshot(db) == before


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "state",
    [
        "archived",
        "foreign",
        "foreign_archived",
        "moved",
        "deleted_parent",
        "deleted_question",
        "missing",
    ],
)
def test_unavailable_or_foreign_parent_preserves_rows_and_error_contract(
    answers_authority, action, state
):
    s = answers_authority
    db = s["db"]
    name = "foreign" if state.startswith("foreign") else None
    qid, aid = target_ids(s, action, name)
    q = db.get(Question, qid)
    parent = db.get(Questionnaire, q.questionnaire_id)
    if action.startswith("create") and aid is not None:
        db.delete(db.get(Answer, aid))
        aid = None
    if state in ("archived", "foreign_archived"):
        parent.deleted_at = datetime.now(timezone.utc)
    elif state == "moved":
        parent.workspace_id = s["other_ws"]
    elif state == "deleted_parent":
        db.delete(parent)
    elif state == "deleted_question":
        db.delete(q)
    elif state == "missing":
        qid = int(db.scalar(select(func.max(Question.id)))) + 100_000
        aid = int(db.scalar(select(func.max(Answer.id)))) + 100_000
    db.commit()
    if state in ("deleted_parent", "deleted_question"):
        db.expire_all()
        assert db.get(Question, qid) is None
        if aid is not None:
            assert db.get(Answer, aid) is None
    if state in ("foreign", "foreign_archived", "moved"):
        status, detail = 403, "Access denied"
    elif state == "archived":
        status, detail = 404, "Referenced resource not found"
    else:
        status, detail = 404, "Answer not found" if action == "patch" else "Question not found"
    with s["client"]() as client:
        denied(s, client, action, qid, aid, status, detail)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "revocation", ["no_review", "suspended", "membership_removed", "session_removed"]
)
def test_individual_writes_use_current_stored_authority(answers_authority, action, revocation):
    s = answers_authority
    qid, aid = target_ids(s, action)
    with s["client"]() as client:
        # Sign first; the original admin cookie must not override current state.
        db = s["db"]
        member = db.get(WorkspaceMember, s["member"])
        if revocation == "no_review":
            member.role = "no-review"
        elif revocation == "suspended":
            member.suspended = True
        elif revocation == "membership_removed":
            db.delete(member)
        else:
            db.delete(db.get(UserSession, s["session"]))
        db.commit()
        denied(s, client, action, qid, aid, 401 if revocation == "session_removed" else 403)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("role", ["admin", "editor", "reviewer"])
def test_available_parent_preserves_success_and_other_answer_fields(
    answers_authority, action, role
):
    s = answers_authority
    qid, aid = target_ids(s, action)
    with s["client"](role) as client:
        before = snapshot(s["db"])
        response = send(client, action, qid, aid)
    assert response.status_code == 200
    assert not response.history and "location" not in response.headers
    row = s["db"].query(Answer).filter(Answer.question_id == qid).one()
    assert response.json() == {
        "id": row.id,
        "question_id": qid,
        "text": "Human replacement",
        "status": "approved",
    }
    values = {"text": "Human replacement", "status": "approved", "outcome_code": None}
    if action.startswith("create"):
        assert_answer_changes(s["db"], before, created={qid: values})
    else:
        assert row.id == aid
        assert_answer_changes(s["db"], before, updates={aid: values})


@pytest.mark.parametrize("action", ["upsert", "upsert-slash"])
@pytest.mark.parametrize(
    "body,expected",
    [
        ({}, {}),
        ({"text": "existing answer"}, {}),
        ({"text": ""}, {}),
        ({"status": "pending"}, {"status": "pending"}),
        ({"status": ""}, {}),
    ],
)
def test_upsert_keeps_existing_empty_text_and_outcome_semantics(
    answers_authority, action, body, expected
):
    s = answers_authority
    qid, aid = target_ids(s, action)
    with s["client"]() as client:
        before = snapshot(s["db"])
        response = send(client, action, qid, aid, body)
    assert response.status_code == 200
    assert response.json() == {
        "id": aid,
        "question_id": qid,
        "text": "existing answer",
        "status": expected.get("status", "draft"),
    }
    assert_answer_changes(s["db"], before, updates={aid: expected})


@pytest.mark.parametrize(
    "body,expected",
    [
        ({}, {}),
        ({"text": None, "status": None}, {}),
        ({"text": "existing answer"}, {}),
        ({"text": ""}, {"text": "", "outcome_code": None}),
        ({"status": "existing-custom-status"}, {"status": "existing-custom-status"}),
        ({"status": ""}, {"status": ""}),
    ],
)
def test_patch_preserves_null_empty_text_status_and_outcome_semantics(
    answers_authority, body, expected
):
    s = answers_authority
    qid, aid = target_ids(s, "patch")
    with s["client"]() as client:
        before = snapshot(s["db"])
        response = send(client, "patch", qid, aid, body)
    assert response.status_code == 200
    assert response.json() == {
        "id": aid,
        "question_id": qid,
        "text": expected.get("text", "existing answer"),
        "status": expected.get("status", "draft"),
    }
    assert_answer_changes(s["db"], before, updates={aid: expected})


@pytest.mark.parametrize("action", ACTIONS)
def test_retry_rechecks_parent_after_a_successful_write(answers_authority, action):
    s = answers_authority
    qid, aid = target_ids(s, action)
    with s["client"]() as client:
        response = send(client, action, qid, aid)
        assert response.status_code == 200
        parent_id = s["db"].get(Question, qid).questionnaire_id
        s["db"].get(Questionnaire, parent_id).deleted_at = datetime.now(timezone.utc)
        s["db"].commit()
        denied(s, client, action, qid, response.json()["id"], 404, "Referenced resource not found")
