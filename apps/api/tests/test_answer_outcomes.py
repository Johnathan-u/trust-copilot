"""Answer delivery outcomes (E6-31)."""

import pytest

from app.models.answer import Answer
from app.models.questionnaire import Question, Questionnaire
from app.services import answer_outcome_service as aos


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


def test_record_and_list_outcome(db_session):
    ws_id = 1
    qnr = Questionnaire(workspace_id=ws_id, filename="outcome-test.csv", status="uploaded")
    db_session.add(qnr)
    db_session.flush()
    q = Question(questionnaire_id=qnr.id, text="Outcome Q?", section=None)
    db_session.add(q)
    db_session.flush()
    ans = Answer(question_id=q.id, text="A", status="approved")
    db_session.add(ans)
    db_session.flush()
    aid = ans.id
    db_session.commit()

    out = aos.record_outcome(
        db_session,
        ws_id,
        aid,
        accepted_without_edits=True,
        was_edited=False,
        follow_up_requested=False,
        deal_closed=True,
        review_cycle_hours=24.0,
        channel="manual",
        notes="Buyer signed off",
        created_by_user_id=1,
    )
    assert out is not None
    assert out["answer_id"] == aid
    db_session.commit()

    listed = aos.list_for_answer(db_session, ws_id, aid)
    assert len(listed) == 1
    assert listed[0]["accepted_without_edits"] is True


def test_record_rejects_wrong_workspace(db_session):
    ws_id = 1
    qnr = Questionnaire(workspace_id=ws_id, filename="ws2.csv", status="uploaded")
    db_session.add(qnr)
    db_session.flush()
    q = Question(questionnaire_id=qnr.id, text="Q", section=None)
    db_session.add(q)
    db_session.flush()
    ans = Answer(question_id=q.id, text="x", status="draft")
    db_session.add(ans)
    db_session.flush()
    aid = ans.id
    db_session.commit()

    bad = aos.record_outcome(db_session, 999, aid, channel="manual")
    assert bad is None


def test_answer_outcomes_api(admin_client, db_session):
    ws_id = 1
    qnr = Questionnaire(workspace_id=ws_id, filename="api-outcome.csv", status="uploaded")
    db_session.add(qnr)
    db_session.flush()
    q = Question(questionnaire_id=qnr.id, text="API outcome Q", section=None)
    db_session.add(q)
    db_session.flush()
    ans = Answer(question_id=q.id, text="Body", status="approved")
    db_session.add(ans)
    db_session.flush()
    aid = ans.id
    db_session.commit()

    admin_client.cookies.clear()
    assert admin_client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"}).status_code == 200

    r = admin_client.post(
        "/api/answer-outcomes",
        json={
            "answer_id": aid,
            "accepted_without_edits": False,
            "was_edited": True,
            "edit_diff_json": '{"kind":"replace","summary":"typo fix"}',
            "channel": "export",
        },
        headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["was_edited"] is True

    g = admin_client.get(f"/api/answer-outcomes/answer/{aid}")
    assert g.status_code == 200
    assert len(g.json()["outcomes"]) == 1

    rec = admin_client.get("/api/answer-outcomes/recent?limit=10")
    assert rec.status_code == 200
    ids = [o["answer_id"] for o in rec.json()["outcomes"]]
    assert aid in ids
