"""TC-17-005: scoped share spaces, revocable grants, and a stable create.

Create and update reject an article, answer, or document id that is missing
or outside the workspace. Token access and token reads return only listed
objects that are still in the workspace: a published article version, an
approved answer, or a live document. Expiry and deactivation stop the
download. A repeated create with the same Idempotency-Key returns the first
space. The stored response is in PostgreSQL, so a later request on a new
connection still returns that space and does not insert another row.
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import text

from app.core.database import SessionLocal
from app.main import app
from app.models.answer import Answer
from app.models.audit_event import AuditEvent
from app.models.document import Document
from app.models.questionnaire import Question, Questionnaire
from app.models.shareable_space import ShareableSpace
from app.models.trust_article import TrustArticle, TrustArticleVersion

_LISTED = b"%PDF-1.4 LISTED-WORKSPACE-BYTES"
_FOREIGN = b"%PDF-1.4 FOREIGN-WORKSPACE-BYTES"
_MISSING = 2147483646
_ACCESS_KEYS = {"valid", "space", "article_ids", "answer_ids", "document_ids"}


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


def _stored_files():
    from app.services.storage import get_storage

    files = _Files()
    app.dependency_overrides[get_storage] = lambda: files
    return files


def _clear_files():
    from app.services.storage import get_storage

    app.dependency_overrides.pop(get_storage, None)


def world(client, db_session):
    """Build one workspace of synthetic assets and remove them afterwards."""
    suffix = secrets.token_hex(4)
    prefix = f"tc17005c-{suffix}"
    owned = {
        "articles": [],
        "versions": [],
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

    def publish(article):
        version = TrustArticleVersion(
            trust_article_id=article.id,
            workspace_id=article.workspace_id,
            version_number=1,
            slug=article.slug,
            title=article.title,
            content=article.content or "",
            category=article.category,
            is_policy=bool(article.is_policy),
        )
        db_session.add(version)
        db_session.flush()
        article.published = 1
        article.published_version_id = version.id
        owned["versions"].append(version.id)
        return version

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

    def add_answer(workspace_id, label, answer_text):
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
        answer = Answer(question_id=question.id, text=answer_text, status="approved")
        db_session.add(answer)
        db_session.flush()
        owned["answers"].append(answer.id)
        return answer

    article = add_article(1, "owned-article", "owned-article-body")
    publish(article)
    foreign_article = add_article(2, "foreign-article", "foreign-article-body")
    listed = add_document(1, "listed")
    foreign_document = add_document(2, "foreign")
    answer = add_answer(1, "owned-answer", "owned-answer-text")
    foreign_answer = add_answer(2, "foreign-answer", "foreign-answer-text")
    bag = {
        "client": client,
        "db": db_session,
        "prefix": prefix,
        "article_id": article.id,
        "article_title": article.title,
        "foreign_article_id": foreign_article.id,
        "listed_id": listed.id,
        "listed_key": listed.storage_key,
        "foreign_document_id": foreign_document.id,
        "foreign_key": foreign_document.storage_key,
        "answer_id": answer.id,
        "foreign_answer_id": foreign_answer.id,
        "owned": owned,
    }
    db_session.commit()
    _login(client, "admin@trust.local", "a")
    return bag


def _cleanup(db_session, bag):
    prefix = bag["prefix"]
    owned = bag["owned"]
    _see(db_session)
    db_session.execute(
        text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :prefix"),
        {"prefix": f"%{prefix}%"},
    )
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
    if owned["versions"]:
        db_session.query(TrustArticleVersion).filter(
            TrustArticleVersion.id.in_(owned["versions"])
        ).delete(synchronize_session=False)
    if owned["articles"]:
        db_session.query(TrustArticleVersion).filter(
            TrustArticleVersion.trust_article_id.in_(owned["articles"])
        ).delete(synchronize_session=False)
        db_session.query(TrustArticle).filter(TrustArticle.id.in_(owned["articles"])).delete(
            synchronize_session=False
        )
    db_session.commit()


def _name(bag, label):
    return f"{bag['prefix']}-{label}"


def _count(bag, name):
    _see(bag["db"])
    return bag["db"].query(ShareableSpace).filter(ShareableSpace.name == name).count()


def _body(bag, name, **lists):
    payload = {"name": name, "buyer_company": "Synthetic Buyer"}
    payload.update(lists)
    return payload


def _key(bag):
    return f"{bag['prefix']}-{uuid.uuid4().hex[:8]}"


def _replay_in_new_process(payload: dict, key: str) -> dict:
    """POST the same create from a new Python process and return the replay flags."""
    code = """
import json, os
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(
    app,
    base_url="http://localhost",
    headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
)
login = client.post(
    "/api/auth/login",
    json={"email": "admin@trust.local", "password": "a"},
)
if login.status_code != 200:
    raise SystemExit("login failed")
response = client.post(
    "/api/shareable-spaces",
    json=json.loads(os.environ["TC_REPLAY_BODY"]),
    headers={"Idempotency-Key": os.environ["TC_REPLAY_KEY"]},
)
if response.status_code != 200:
    raise SystemExit("create failed")
body = response.json()
print("TC17005C_REPLAY " + json.dumps({
    "id": body["id"],
    "token_null": body.get("access_token") is None,
    "token_available": body.get("token_available"),
}))
"""
    env = os.environ.copy()
    env["TC_REPLAY_BODY"] = json.dumps(payload)
    env["TC_REPLAY_KEY"] = key
    api_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-500:]
    line = next(
        item for item in completed.stdout.splitlines() if item.startswith("TC17005C_REPLAY ")
    )
    return json.loads(line.removeprefix("TC17005C_REPLAY "))


def test_create_rejects_ids_outside_the_workspace(client, db_session):
    """A foreign or missing id is 404 and leaves no space row."""
    bag = world(client, db_session)
    try:
        cases = (
            ("article_ids", bag["foreign_article_id"], "Article not found"),
            ("answer_ids", bag["foreign_answer_id"], "Answer not found"),
            ("document_ids", bag["foreign_document_id"], "Document not found"),
            ("article_ids", _MISSING, "Article not found"),
            ("document_ids", _MISSING, "Document not found"),
        )
        for index, (field, asset_id, detail) in enumerate(cases):
            name = _name(bag, f"reject-{index}")
            response = client.post(
                "/api/shareable-spaces", json=_body(bag, name, **{field: [asset_id]})
            )
            assert _count(bag, name) == 0
            assert response.status_code == 404
            assert response.json()["detail"] == detail
        mixed = _name(bag, "mixed")
        response = client.post(
            "/api/shareable-spaces",
            json=_body(
                bag,
                mixed,
                article_ids=[bag["article_id"]],
                answer_ids=[bag["answer_id"]],
                document_ids=[bag["foreign_document_id"]],
            ),
        )
        assert _count(bag, mixed) == 0
        assert response.status_code == 404
        assert response.json()["detail"] == "Document not found"
    finally:
        client.cookies.clear()
        _cleanup(db_session, bag)


def test_editor_cannot_create(client, db_session):
    """An editor is 403 and no row is written."""
    bag = world(client, db_session)
    try:
        _login(client, "editor@trust.local", "e")
        name = _name(bag, "editor")
        response = client.post(
            "/api/shareable-spaces",
            json=_body(bag, name, article_ids=[bag["article_id"]]),
        )
        assert response.status_code == 403
        assert _count(bag, name) == 0
    finally:
        client.cookies.clear()
        _cleanup(db_session, bag)


def test_access_returns_listed_published_assets_and_hides_the_rest(client, db_session):
    """The token payload and the token reads agree, and a draft is not served."""
    bag = world(client, db_session)
    files = _stored_files()
    files.objects[("raw", bag["listed_key"])] = _LISTED
    files.objects[("raw", bag["foreign_key"])] = _FOREIGN
    db = db_session
    unpublished = TrustArticle(
        workspace_id=1,
        slug=f"{bag['prefix']}-unpublished",
        title=f"unpublished-{bag['prefix']}",
        content="UNPUBLISHED-ARTICLE-BODY",
        published=0,
    )
    db.add(unpublished)
    db.flush()
    bag["owned"]["articles"].append(unpublished.id)
    hidden_version = TrustArticleVersion(
        trust_article_id=unpublished.id,
        workspace_id=1,
        version_number=1,
        slug=unpublished.slug,
        title="Published title that must stay hidden",
        content="UNPUBLISHED-VERSION-BODY",
        is_policy=False,
    )
    db.add(hidden_version)
    db.flush()
    bag["owned"]["versions"].append(hidden_version.id)
    unpublished.published_version_id = hidden_version.id
    questionnaire = Questionnaire(
        workspace_id=1,
        filename=f"{bag['prefix']}-draft.xlsx",
        status="parsed",
    )
    db.add(questionnaire)
    db.flush()
    bag["owned"]["questionnaires"].append(questionnaire.id)
    question = Question(questionnaire_id=questionnaire.id, text=f"draft {bag['prefix']}")
    db.add(question)
    db.flush()
    bag["owned"]["questions"].append(question.id)
    draft = Answer(question_id=question.id, text="DRAFT-ANSWER-TEXT", status="draft")
    db.add(draft)
    db.flush()
    bag["owned"]["answers"].append(draft.id)
    db.commit()
    try:
        name = _name(bag, "listed")
        created = client.post(
            "/api/shareable-spaces",
            json=_body(
                bag,
                name,
                article_ids=[bag["article_id"], unpublished.id],
                answer_ids=[bag["answer_id"], draft.id],
                document_ids=[bag["listed_id"]],
            ),
        )
        assert created.status_code == 200, created.text
        raw = created.json()["access_token"]
        assert isinstance(raw, str) and raw
        space_id = created.json()["id"]
        _see(db)
        stored = db.get(ShareableSpace, space_id)
        assert stored.access_token is None
        assert stored.token_hash == _digest(raw)

        client.cookies.clear()
        opened = client.get("/api/shareable-spaces/access", params={"token": raw})
        assert opened.status_code == 200
        body = opened.json()
        assert set(body) == _ACCESS_KEYS
        assert body["valid"] is True
        assert body["space"]["id"] == space_id
        assert body["space"]["name"] == name
        assert body["space"]["access_token"] is None
        assert body["article_ids"] == [bag["article_id"]]
        assert unpublished.id not in body["article_ids"]
        assert body["answer_ids"] == [bag["answer_id"]]
        assert draft.id not in body["answer_ids"]
        assert body["document_ids"] == [bag["listed_id"]]
        assert raw not in opened.text
        assert "UNPUBLISHED-ARTICLE-BODY" not in opened.text
        assert "DRAFT-ANSWER-TEXT" not in opened.text

        article = client.get(
            f"/api/shareable-spaces/access/articles/{bag['article_id']}",
            params={"token": raw},
        )
        assert article.status_code == 200
        assert article.json() == {
            "id": bag["article_id"],
            "title": bag["article_title"],
            "content": "owned-article-body",
        }
        hidden = client.get(
            f"/api/shareable-spaces/access/articles/{unpublished.id}",
            params={"token": raw},
        )
        assert hidden.status_code == 404
        assert "UNPUBLISHED-VERSION-BODY" not in hidden.text
        answer = client.get(
            f"/api/shareable-spaces/access/answers/{bag['answer_id']}",
            params={"token": raw},
        )
        assert answer.status_code == 200
        assert answer.json() == {
            "id": bag["answer_id"],
            "text": "owned-answer-text",
            "status": "approved",
        }
        draft_read = client.get(
            f"/api/shareable-spaces/access/answers/{draft.id}",
            params={"token": raw},
        )
        assert draft_read.status_code == 404
        assert "DRAFT-ANSWER-TEXT" not in draft_read.text
        foreign = client.get(
            f"/api/shareable-spaces/access/articles/{bag['foreign_article_id']}",
            params={"token": raw},
        )
        assert foreign.status_code == 404
        assert "foreign-article-body" not in foreign.text

        listed = client.get(
            f"/api/shareable-spaces/access/documents/{bag['listed_id']}/content",
            params={"token": raw},
        )
        assert listed.status_code == 200
        assert listed.content == _LISTED
        other = client.get(
            f"/api/shareable-spaces/access/documents/{bag['foreign_document_id']}/content",
            params={"token": raw},
        )
        assert other.status_code == 404
        assert _FOREIGN not in other.content
        reviewer = client.get(
            f"/api/documents/{bag['listed_id']}/content",
            params={"workspace_id": 1, "token": raw},
        )
        assert reviewer.status_code == 401
        assert _LISTED not in reviewer.content

        article_row = db.get(TrustArticle, bag["article_id"])
        article_row.title = "Draft title"
        article_row.content = "DRAFT-ARTICLE-BODY"
        db.commit()
        client.cookies.clear()
        reread = client.get(
            f"/api/shareable-spaces/access/articles/{bag['article_id']}",
            params={"token": raw},
        )
        assert reread.status_code == 200
        assert reread.json()["title"] == bag["article_title"]
        assert reread.json()["content"] == "owned-article-body"
        assert "DRAFT-ARTICLE-BODY" not in reread.text
    finally:
        _clear_files()
        client.cookies.clear()
        _cleanup(db_session, bag)


def test_deactivate_and_expiry_stop_the_download(client, db_session):
    """Turning the space off, or letting it expire, makes the previous download fail."""
    bag = world(client, db_session)
    files = _stored_files()
    files.objects[("raw", bag["listed_key"])] = _LISTED
    try:
        name = _name(bag, "revoke")
        created = client.post(
            "/api/shareable-spaces",
            json=_body(bag, name, document_ids=[bag["listed_id"]]),
        )
        assert created.status_code == 200, created.text
        raw = created.json()["access_token"]
        space_id = created.json()["id"]
        client.cookies.clear()
        opened = client.get(
            f"/api/shareable-spaces/access/documents/{bag['listed_id']}/content",
            params={"token": raw},
        )
        assert opened.status_code == 200
        assert opened.content == _LISTED
        _login(client, "admin@trust.local", "a")
        deactivated = client.post(f"/api/shareable-spaces/{space_id}/deactivate")
        assert deactivated.status_code == 200
        client.cookies.clear()
        denied = client.get(
            f"/api/shareable-spaces/access/documents/{bag['listed_id']}/content",
            params={"token": raw},
        )
        assert denied.status_code == 404
        assert denied.json()["detail"] == "Not found"
        assert _LISTED not in denied.content
        access = client.get("/api/shareable-spaces/access", params={"token": raw})
        assert access.json()["valid"] is False
        assert access.json()["reason"] == "Space deactivated"

        expired_raw = secrets.token_urlsafe(32)
        row = ShareableSpace(
            workspace_id=1,
            name=_name(bag, "expired"),
            access_token=None,
            token_hash=_digest(expired_raw),
            is_active=True,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
            article_ids_json=json.dumps([]),
            answer_ids_json=json.dumps([]),
            document_ids_json=json.dumps([bag["listed_id"]]),
        )
        db_session.add(row)
        db_session.commit()
        expired = client.get(
            f"/api/shareable-spaces/access/documents/{bag['listed_id']}/content",
            params={"token": expired_raw},
        )
        assert expired.status_code == 404
        assert _LISTED not in expired.content
        expired_access = client.get("/api/shareable-spaces/access", params={"token": expired_raw})
        assert expired_access.json()["valid"] is False
        assert expired_access.json()["reason"] == "Space expired"
    finally:
        _clear_files()
        client.cookies.clear()
        _cleanup(db_session, bag)


def test_retried_create_returns_the_original_space(client, db_session):
    """The same Idempotency-Key inserts one row and returns that response again.

    A new database session is what the API opens after a restart. The retry
    reads the stored response from that session's database and does not insert
    a second space.
    """
    bag = world(client, db_session)
    name = _name(bag, "retry")
    key = _key(bag)
    headers = {"Idempotency-Key": key}
    payload = _body(
        bag,
        name,
        article_ids=[bag["article_id"]],
        answer_ids=[bag["answer_id"]],
        document_ids=[bag["listed_id"]],
    )
    try:
        first = client.post("/api/shareable-spaces", json=payload, headers=headers)
        assert first.status_code == 200, first.text
        assert "_request_hash" not in first.json()
        raw = first.json()["access_token"]
        assert isinstance(raw, str) and raw
        second = client.post("/api/shareable-spaces", json=payload, headers=headers)
        assert second.status_code == 200, second.text
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["name"] == name
        assert second.json()["access_token"] is None
        assert second.json()["token_available"] is False
        assert raw not in second.text
        assert _count(bag, name) == 1
        _see(db_session)
        stored = db_session.get(ShareableSpace, first.json()["id"])
        assert stored.access_token is None

        fresh = SessionLocal()
        try:
            fresh_count = fresh.query(ShareableSpace).filter(ShareableSpace.name == name).count()
            saved = fresh.execute(
                text(
                    "SELECT status_code, response_body FROM idempotency_keys "
                    "WHERE idempotency_key LIKE :prefix"
                ),
                {"prefix": f"%{key}"},
            ).one()
        finally:
            fresh.close()
        assert fresh_count == 1
        assert saved[0] == 200
        recorded = saved[1]
        assert str(first.json()["id"]) in recorded
        assert raw not in recorded
        assert quote(raw, safe="") not in recorded
        assert f"token={raw}" not in recorded
        assert "/share?" not in recorded

        # A new interpreter is a restarted API process. It has no memory of the
        # first request and reads the stored response from PostgreSQL.
        replayed = _replay_in_new_process(payload, key)
        assert replayed["id"] == first.json()["id"]
        assert replayed["token_null"] is True
        assert replayed["token_available"] is False
        assert _count(bag, name) == 1

        changed = dict(payload)
        changed["buyer_company"] = "Other Buyer"
        conflict = client.post("/api/shareable-spaces", json=changed, headers=headers)
        assert conflict.status_code == 422
        assert "different request body" in conflict.json()["detail"]
        assert _count(bag, name) == 1

        invalid = client.post(
            "/api/shareable-spaces",
            json=payload,
            headers={"Idempotency-Key": "has space"},
        )
        assert invalid.status_code == 422
        assert _count(bag, name) == 1
    finally:
        client.cookies.clear()
        _cleanup(db_session, bag)


def test_partial_failure_writes_nothing_and_the_key_can_be_retried(client, db_session):
    """A bad id writes no row. The same key can then create the corrected space once."""
    bag = world(client, db_session)
    name = _name(bag, "partial")
    key = _key(bag)
    headers = {"Idempotency-Key": key}
    bad = _body(
        bag,
        name,
        article_ids=[bag["article_id"]],
        document_ids=[bag["foreign_document_id"]],
    )
    good = _body(
        bag,
        name,
        article_ids=[bag["article_id"]],
        answer_ids=[bag["answer_id"]],
        document_ids=[bag["listed_id"]],
    )
    try:
        denied = client.post("/api/shareable-spaces", json=bad, headers=headers)
        assert denied.status_code == 404
        assert denied.json()["detail"] == "Document not found"
        assert _count(bag, name) == 0
        again = client.post("/api/shareable-spaces", json=bad, headers=headers)
        assert again.status_code == 404
        assert _count(bag, name) == 0
        created = client.post("/api/shareable-spaces", json=good, headers=headers)
        assert created.status_code == 200, created.text
        replay = client.post("/api/shareable-spaces", json=good, headers=headers)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == created.json()["id"]
        assert replay.json()["access_token"] is None
        assert replay.json()["token_available"] is False
        assert _count(bag, name) == 1
    finally:
        client.cookies.clear()
        _cleanup(db_session, bag)
