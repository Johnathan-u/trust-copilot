"""TC-17-005b: listed share assets stay inside the space's workspace.

Create and update reject an article, answer, or document id that is missing,
deleted, or owned by another workspace, and they do not write that change.
Token access returns only ids that still belong to the space. Token reads and
the original download serve only the objects listed on that live space.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from app.models.answer import Answer
from app.models.audit_event import AuditEvent
from app.models.document import Document
from app.models.questionnaire import Question, Questionnaire
from app.models.shareable_space import ShareableSpace
from app.models.trust_article import TrustArticle

_LISTED = b"%PDF-1.4 LISTED-WORKSPACE-BYTES"
_UNLISTED = b"%PDF-1.4 UNLISTED-WORKSPACE-BYTES"
_FOREIGN = b"%PDF-1.4 FOREIGN-WORKSPACE-BYTES"
_MISSING = 2147483646


def _login(client, email, password):
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return client


def _see(db):
    db.rollback()
    db.expire_all()


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class _Files:
    def __init__(self):
        self.bucket_raw = "raw"
        self.objects = {}

    def download_stream(self, bucket, key):
        body = self.objects.get((bucket, key))
        if body is None:
            raise FileNotFoundError(key)
        return iter([body])


@pytest.fixture
def stored_files():
    from app.main import app
    from app.services.storage import get_storage

    files = _Files()
    app.dependency_overrides[get_storage] = lambda: files
    try:
        yield files
    finally:
        app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def world(client, db_session):
    suffix = secrets.token_hex(4)
    prefix = f"tc17005b-{suffix}"
    owned = {
        "articles": [],
        "documents": [],
        "questionnaires": [],
        "questions": [],
        "answers": [],
    }

    def add_article(workspace_id, label, body):
        row = TrustArticle(
            workspace_id=workspace_id,
            slug=f"{prefix}-{label}",
            title=f"{label}-{suffix}",
            content=body,
            published=1,
        )
        db_session.add(row)
        db_session.flush()
        owned["articles"].append(row.id)
        return row

    def add_document(workspace_id, label, *, deleted=False):
        row = Document(
            workspace_id=workspace_id,
            storage_key=f"synthetic/{prefix}/{label}.pdf",
            filename=f"{label}.pdf",
            content_type="application/pdf",
            status="uploaded",
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
        db_session.add(row)
        db_session.flush()
        owned["documents"].append(row.id)
        return row

    def add_answer(workspace_id, label, text):
        questionnaire = Questionnaire(
            workspace_id=workspace_id,
            filename=f"{prefix}-{label}.xlsx",
            status="parsed",
        )
        db_session.add(questionnaire)
        db_session.flush()
        owned["questionnaires"].append(questionnaire.id)
        question = Question(questionnaire_id=questionnaire.id, text=f"{label} {suffix}")
        db_session.add(question)
        db_session.flush()
        owned["questions"].append(question.id)
        answer = Answer(question_id=question.id, text=text, status="approved")
        db_session.add(answer)
        db_session.flush()
        owned["answers"].append(answer.id)
        return answer, questionnaire

    article = add_article(1, "owned-article", "owned-article-body")
    foreign_article = add_article(2, "foreign-article", "foreign-article-body")
    listed = add_document(1, "listed")
    unlisted = add_document(1, "unlisted")
    deleted = add_document(1, "deleted", deleted=True)
    foreign_document = add_document(2, "foreign")
    answer, questionnaire = add_answer(1, "owned-answer", "owned-answer-text")
    foreign_answer, _foreign_qnr = add_answer(2, "foreign-answer", "foreign-answer-text")
    bag = {
        "client": client,
        "db": db_session,
        "prefix": prefix,
        "article_id": article.id,
        "article_title": article.title,
        "foreign_article_id": foreign_article.id,
        "listed_id": listed.id,
        "listed_key": listed.storage_key,
        "unlisted_id": unlisted.id,
        "unlisted_key": unlisted.storage_key,
        "deleted_id": deleted.id,
        "foreign_document_id": foreign_document.id,
        "foreign_key": foreign_document.storage_key,
        "answer_id": answer.id,
        "foreign_answer_id": foreign_answer.id,
        "questionnaire_id": questionnaire.id,
    }
    db_session.commit()
    _login(client, "admin@trust.local", "a")
    try:
        yield bag
    finally:
        client.cookies.clear()
        _see(db_session)
        space_ids = [
            row[0]
            for row in db_session.query(ShareableSpace.id)
            .filter(ShareableSpace.name.like(f"{prefix}%"))
            .all()
        ]
        if space_ids:
            db_session.query(AuditEvent).filter(
                AuditEvent.resource_type == "shareable_space",
                AuditEvent.resource_id.in_([str(item) for item in space_ids]),
            ).delete(synchronize_session=False)
            db_session.query(ShareableSpace).filter(ShareableSpace.id.in_(space_ids)).delete(
                synchronize_session=False
            )
        if owned["answers"]:
            db_session.query(Answer).filter(Answer.id.in_(owned["answers"])).delete(
                synchronize_session=False
            )
        if owned["questions"]:
            db_session.query(Question).filter(Question.id.in_(owned["questions"])).delete(
                synchronize_session=False
            )
        if owned["questionnaires"]:
            db_session.query(Questionnaire).filter(
                Questionnaire.id.in_(owned["questionnaires"])
            ).delete(synchronize_session=False)
        if owned["documents"]:
            db_session.query(Document).filter(Document.id.in_(owned["documents"])).delete(
                synchronize_session=False
            )
        if owned["articles"]:
            db_session.query(TrustArticle).filter(TrustArticle.id.in_(owned["articles"])).delete(
                synchronize_session=False
            )
        db_session.commit()


def _name(world, label):
    return f"{world['prefix']}-{label}"


def _create(world, name, **lists):
    body = {"name": name, "buyer_company": "Synthetic Buyer"}
    body.update(lists)
    return world["client"].post("/api/shareable-spaces", json=body)


def _count(world, name):
    _see(world["db"])
    return world["db"].query(ShareableSpace).filter(ShareableSpace.name == name).count()


def _row(world, space_id):
    _see(world["db"])
    return world["db"].get(ShareableSpace, space_id)


def _lists(row):
    return (
        row.article_ids_json,
        row.answer_ids_json,
        row.document_ids_json,
        row.token_hash,
        row.updated_at,
        row.workspace_id,
        row.name,
    )


def _legacy(world, **columns):
    raw = secrets.token_urlsafe(32)
    expired = columns.pop("expired", False)
    active = columns.pop("active", True)
    when = datetime.now(timezone.utc).replace(tzinfo=None)
    when = when - timedelta(days=1) if expired else when + timedelta(days=3)
    row = ShareableSpace(
        workspace_id=columns.pop("workspace_id", 1),
        name=columns.pop("name"),
        access_token=None,
        token_hash=_digest(raw),
        is_active=active,
        expires_at=when,
        article_ids_json=json.dumps(columns.pop("article_ids", [])),
        answer_ids_json=json.dumps(columns.pop("answer_ids", [])),
        document_ids_json=json.dumps(columns.pop("document_ids", [])),
    )
    world["db"].add(row)
    world["db"].commit()
    world["db"].refresh(row)
    return raw, row.id


def _download(client, document_id, token):
    return client.get(
        f"/api/shareable-spaces/access/documents/{document_id}/content",
        params={"token": token},
    )


def _fill(stored_files, world):
    stored_files.objects[("raw", world["listed_key"])] = _LISTED
    stored_files.objects[("raw", world["unlisted_key"])] = _UNLISTED
    stored_files.objects[("raw", world["foreign_key"])] = _FOREIGN


def test_create_rejects_ids_outside_the_workspace(world):
    cases = (
        ("article_ids", world["foreign_article_id"], "Article not found"),
        ("answer_ids", world["foreign_answer_id"], "Answer not found"),
        ("document_ids", world["foreign_document_id"], "Document not found"),
        ("article_ids", _MISSING, "Article not found"),
        ("answer_ids", _MISSING, "Answer not found"),
        ("document_ids", _MISSING, "Document not found"),
        ("document_ids", world["deleted_id"], "Document not found"),
    )
    for index, (field, asset_id, detail) in enumerate(cases):
        name = _name(world, f"reject-{index}")
        response = _create(world, name, **{field: [asset_id]})
        assert _count(world, name) == 0
        assert response.status_code == 404
        assert response.json()["detail"] == detail

    mixed = _name(world, "mixed")
    response = _create(
        world,
        mixed,
        article_ids=[world["article_id"]],
        answer_ids=[world["answer_id"]],
        document_ids=[world["foreign_document_id"]],
    )
    assert _count(world, mixed) == 0
    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


def test_create_stores_ids_that_belong_to_the_workspace(world):
    name = _name(world, "owned")
    response = _create(
        world,
        name,
        article_ids=[world["article_id"]],
        answer_ids=[world["answer_id"]],
        document_ids=[world["listed_id"]],
    )
    assert response.status_code == 200
    raw = response.json()["access_token"]
    assert isinstance(raw, str) and raw
    world["client"].cookies.clear()
    opened = world["client"].get("/api/shareable-spaces/access", params={"token": raw})
    assert opened.status_code == 200
    body = opened.json()
    assert body["valid"] is True
    assert body["article_ids"] == [world["article_id"]]
    assert body["answer_ids"] == [world["answer_id"]]
    assert body["document_ids"] == [world["listed_id"]]
    assert raw not in opened.text


def test_update_rejects_foreign_ids_and_keeps_the_saved_lists(world, stored_files):
    _fill(stored_files, world)
    name = _name(world, "update")
    created = _create(
        world,
        name,
        article_ids=[world["article_id"]],
        answer_ids=[world["answer_id"]],
        document_ids=[world["listed_id"]],
    )
    assert created.status_code == 200
    space_id = created.json()["id"]
    raw = created.json()["access_token"]
    before = _lists(_row(world, space_id))
    foreign_lists = (
        ({"document_ids": [world["foreign_document_id"]]}, "Document not found"),
        ({"article_ids": [world["foreign_article_id"]]}, "Article not found"),
        ({"answer_ids": [_MISSING]}, "Answer not found"),
        ({"document_ids": [world["deleted_id"]]}, "Document not found"),
        (
            {"article_ids": [world["article_id"]], "document_ids": [world["foreign_document_id"]]},
            "Document not found",
        ),
    )
    for payload, detail in foreign_lists:
        response = world["client"].patch(f"/api/shareable-spaces/{space_id}", json=payload)
        assert response.status_code == 404
        assert response.json()["detail"] == detail
        assert _lists(_row(world, space_id)) == before

    _login(world["client"], "editor@trust.local", "e")
    denied = world["client"].patch(
        f"/api/shareable-spaces/{space_id}",
        json={"document_ids": [world["unlisted_id"]]},
    )
    assert denied.status_code == 403
    assert _lists(_row(world, space_id)) == before

    _login(world["client"], "admin@trust.local", "a")
    replaced = world["client"].patch(
        f"/api/shareable-spaces/{space_id}",
        json={"document_ids": [world["unlisted_id"]]},
    )
    assert replaced.status_code == 200
    assert replaced.json()["access_token"] is None
    assert replaced.json()["has_access_token"] is True
    assert raw not in replaced.text
    saved = _row(world, space_id)
    assert saved.article_ids_json == before[0]
    assert saved.answer_ids_json == before[1]
    assert json.loads(saved.document_ids_json) == [world["unlisted_id"]]
    world["client"].cookies.clear()
    opened = world["client"].get("/api/shareable-spaces/access", params={"token": raw})
    assert opened.json()["document_ids"] == [world["unlisted_id"]]
    assert opened.json()["article_ids"] == [world["article_id"]]
    old = _download(world["client"], world["listed_id"], raw)
    new = _download(world["client"], world["unlisted_id"], raw)
    assert old.status_code == 404
    assert _LISTED not in old.content
    assert new.status_code == 200
    assert new.content == _UNLISTED


def test_other_workspace_update_is_not_found(world):
    raw, space_id = _legacy(
        world,
        name=_name(world, "foreign-space"),
        workspace_id=2,
        document_ids=[world["foreign_document_id"]],
        article_ids=[world["foreign_article_id"]],
    )
    before = _lists(_row(world, space_id))
    response = world["client"].patch(
        f"/api/shareable-spaces/{space_id}",
        json={"document_ids": [world["listed_id"]]},
    )
    assert response.status_code == 404
    assert _name(world, "foreign-space") not in response.text
    assert raw not in response.text
    assert _lists(_row(world, space_id)) == before


def test_token_access_omits_ids_from_outside_the_workspace(world):
    raw, _space_id = _legacy(
        world,
        name=_name(world, "stale-lists"),
        article_ids=[world["article_id"], world["foreign_article_id"], _MISSING],
        answer_ids=[world["foreign_answer_id"], world["answer_id"]],
        document_ids=[world["foreign_document_id"], world["listed_id"], world["deleted_id"]],
    )
    world["client"].cookies.clear()
    opened = world["client"].get("/api/shareable-spaces/access", params={"token": raw})
    assert opened.status_code == 200
    body = opened.json()
    assert body["valid"] is True
    assert body["article_ids"] == [world["article_id"]]
    assert body["answer_ids"] == [world["answer_id"]]
    assert body["document_ids"] == [world["listed_id"]]
    assert world["foreign_article_id"] not in body["article_ids"]
    assert world["foreign_answer_id"] not in body["answer_ids"]
    assert world["foreign_document_id"] not in body["document_ids"]
    assert "foreign-article-body" not in opened.text
    assert "foreign-answer-text" not in opened.text
    assert raw not in opened.text


def test_token_download_serves_only_the_listed_document(world, stored_files):
    _fill(stored_files, world)
    raw, _space_id = _legacy(
        world,
        name=_name(world, "download"),
        document_ids=[world["listed_id"], world["foreign_document_id"]],
    )
    other_raw, _other = _legacy(
        world,
        name=_name(world, "other-download"),
        workspace_id=2,
        document_ids=[world["listed_id"], world["foreign_document_id"]],
    )
    world["client"].cookies.clear()
    listed = _download(world["client"], world["listed_id"], raw)
    assert listed.status_code == 200
    assert listed.content == _LISTED
    assert world["listed_key"] not in listed.text
    assert _FOREIGN not in listed.content
    unlisted = _download(world["client"], world["unlisted_id"], raw)
    foreign = _download(world["client"], world["foreign_document_id"], raw)
    deleted = _download(world["client"], world["deleted_id"], raw)
    missing = _download(world["client"], _MISSING, raw)
    via_other = _download(world["client"], world["listed_id"], other_raw)
    for denied in (unlisted, foreign, deleted, missing, via_other):
        assert denied.status_code == 404
        assert denied.json()["detail"] == "Not found"
        assert _LISTED not in denied.content
        assert _UNLISTED not in denied.content
        assert _FOREIGN not in denied.content
        assert world["foreign_key"] not in denied.text


def test_expired_and_inactive_tokens_cannot_download(world, stored_files):
    _fill(stored_files, world)
    expired_raw, _expired = _legacy(
        world,
        name=_name(world, "expired"),
        document_ids=[world["listed_id"]],
        expired=True,
    )
    inactive_raw, _inactive = _legacy(
        world,
        name=_name(world, "inactive"),
        document_ids=[world["listed_id"]],
        active=False,
    )
    world["client"].cookies.clear()
    expired = _download(world["client"], world["listed_id"], expired_raw)
    inactive = _download(world["client"], world["listed_id"], inactive_raw)
    assert expired.status_code == 404
    assert inactive.status_code == 404
    assert expired.json()["detail"] == "Not found"
    assert inactive.json()["detail"] == "Not found"
    assert _LISTED not in expired.content
    assert _LISTED not in inactive.content


def test_token_reads_serve_only_listed_articles_and_answers(world):
    raw, _space_id = _legacy(
        world,
        name=_name(world, "reads"),
        article_ids=[world["article_id"], world["foreign_article_id"]],
        answer_ids=[world["answer_id"], world["foreign_answer_id"]],
    )
    world["client"].cookies.clear()
    article = world["client"].get(
        f"/api/shareable-spaces/access/articles/{world['article_id']}",
        params={"token": raw},
    )
    assert article.status_code == 200
    assert article.json() == {
        "id": world["article_id"],
        "title": world["article_title"],
        "content": "owned-article-body",
    }
    answer = world["client"].get(
        f"/api/shareable-spaces/access/answers/{world['answer_id']}",
        params={"token": raw},
    )
    assert answer.status_code == 200
    assert answer.json() == {
        "id": world["answer_id"],
        "text": "owned-answer-text",
        "status": "approved",
    }
    hidden_article = world["client"].get(
        f"/api/shareable-spaces/access/articles/{world['foreign_article_id']}",
        params={"token": raw},
    )
    hidden_answer = world["client"].get(
        f"/api/shareable-spaces/access/answers/{world['foreign_answer_id']}",
        params={"token": raw},
    )
    unlisted_article = world["client"].get(
        f"/api/shareable-spaces/access/articles/{world['article_id']}",
        params={"token": "not-a-listed-space"},
    )
    for denied in (hidden_article, hidden_answer, unlisted_article):
        assert denied.status_code == 404
        assert denied.json()["detail"] == "Not found"
        assert "foreign-article-body" not in denied.text
        assert "foreign-answer-text" not in denied.text
        assert "owned-article-body" not in denied.text
        assert raw not in denied.text


def test_share_token_does_not_unlock_the_reviewer_download(world, stored_files):
    _fill(stored_files, world)
    raw, _space_id = _legacy(
        world,
        name=_name(world, "reviewer-route"),
        document_ids=[world["listed_id"]],
    )
    world["client"].cookies.clear()
    response = world["client"].get(
        f"/api/documents/{world['listed_id']}/content",
        params={"workspace_id": 1, "token": raw},
    )
    assert response.status_code == 401
    assert _LISTED not in response.content
