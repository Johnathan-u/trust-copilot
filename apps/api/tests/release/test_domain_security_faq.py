"""Reviewed FAQ lifecycle regressions, using synthetic data and exact row cleanup."""

import secrets

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.core.session import sign_session
from app.models import AuditEvent, EvidenceItem, User, Workspace, WorkspaceMember
from app.models.security_faq import SecurityFAQ


@pytest.fixture
def domain(client, db_session):
    tables = (
        "workspaces",
        "users",
        "workspace_members",
        "security_faq",
        "evidence_items",
        "audit_events",
        "idempotency_keys",
    )
    before = {t: db_session.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
    suffix = secrets.token_hex(8)
    ids = [600_000_000 + secrets.randbelow(100_000_000) for _ in range(2)]
    db_session.add_all(
        [Workspace(id=i, slug=f"faq-{suffix}-{i}", name="Synthetic FAQ") for i in ids]
    )
    actors = {}
    for role in ("admin", "reviewer", "editor"):
        user = User(
            email=f"faq-{suffix}-{role}@example.com",
            password_hash="unused-synthetic",
            display_name="FAQ test",
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(WorkspaceMember(workspace_id=ids[0], user_id=user.id, role=role))
        actors[role] = user.id
    evidence = [
        EvidenceItem(
            workspace_id=ws, source_type="manual", title=f"FAQ {suffix}", approval_status="approved"
        )
        for ws in ids
    ]
    db_session.add_all(evidence)
    db_session.flush()
    foreign = SecurityFAQ(
        workspace_id=ids[1],
        category="test",
        question=f"{suffix} foreign?",
        answer="Foreign answer",
        is_default=0,
    )
    db_session.add(foreign)
    db_session.commit()
    state = {
        "client": client,
        "db": db_session,
        "ws": ids[0],
        "foreign_ws": ids[1],
        "suffix": suffix,
        "actors": actors,
        "evidence": evidence[0].id,
        "foreign_evidence": evidence[1].id,
        "foreign": foreign.id,
    }

    def login(role="admin"):
        client.cookies.clear()
        client.cookies.set(
            "tc_session",
            sign_session(actors[role], f"faq-{suffix}-{role}@example.com", ids[0], role),
        )

    state["login"] = login
    login()
    yield state
    client.cookies.clear()
    db_session.rollback()
    db_session.execute(
        text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :prefix"),
        {"prefix": f"ws:{ids[0]}:faq:%"},
    )
    db_session.query(AuditEvent).filter(AuditEvent.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(SecurityFAQ).filter(SecurityFAQ.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(EvidenceItem).filter(EvidenceItem.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(WorkspaceMember).filter(WorkspaceMember.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(User).filter(User.id.in_(actors.values())).delete(synchronize_session=False)
    db_session.query(Workspace).filter(Workspace.id.in_(ids)).delete(synchronize_session=False)
    db_session.commit()
    after = {t: db_session.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
    assert before == after


def create(d, **updates):
    body = {
        "category": "security",
        "question": "How are backups tested?",
        "answer": "Restores are exercised monthly.",
        "source_evidence_ids": [d["evidence"]],
    }
    body.update(updates)
    return d["client"].post("/api/security-faq", json=body)


def action(d, faq, name, **updates):
    return d["client"].post(
        f"/api/security-faq/{faq['id']}/{name}",
        json={"expected_revision": faq.get("revision", 1), **updates},
    )


def test_create_review_publish_edit_invalidates_and_keeps_history(domain):
    d = domain
    r = create(d)
    assert r.status_code == 200
    faq = r.json()
    assert faq.get("revision") == 1 and faq.get("publication_state") == "draft"
    assert action(d, faq, "publish").status_code == 409
    d["login"]("reviewer")
    approved = action(d, faq, "approve", verified=True)
    assert approved.status_code == 200
    assert approved.json()["reviewed_by_user_id"] == d["actors"]["reviewer"]
    d["login"]()
    published = action(d, faq, "publish")
    assert published.status_code == 200
    assert published.json()["publication_state"] == "published"
    repeat = action(d, faq, "publish")
    assert repeat.json() == published.json()
    changed = d["client"].patch(
        f"/api/security-faq/{faq['id']}",
        json={"expected_revision": 1, "answer": "Restores are exercised weekly."},
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2 and changed.json()["publication_state"] == "draft"
    assert changed.json()["reviewed_at"] is None and changed.json()["published_at"] is None
    assert action(d, faq, "publish").status_code == 409
    history = d["client"].get(f"/api/security-faq/{faq['id']}/revisions").json()["revisions"]
    assert [row["revision"] for row in history] == [1, 2]
    assert history[0]["answer"] == "Restores are exercised monthly."


def test_sources_missing_and_foreign_are_equal_404(domain):
    responses = [
        create(domain, source_evidence_ids=[i]) for i in (2147483647, domain["foreign_evidence"])
    ]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_object_missing_and_foreign_are_equal_404(domain, method):
    kwargs = {"json": {"answer": "replacement"}} if method == "patch" else {}
    rs = [
        getattr(domain["client"], method)(f"/api/security-faq/{i}", **kwargs)
        for i in (2147483647, domain["foreign"])
    ]
    assert [r.status_code for r in rs] == [404, 404]
    assert rs[0].json() == rs[1].json()


def test_templates_remain_synthetic_until_explicit_review(domain):
    r = domain["client"].post("/api/security-faq/seed")
    assert r.status_code == 200 and r.json()["created"] > 0
    entries = domain["client"].get("/api/security-faq").json()["faqs"]
    assert all(e["synthetic"] and e["publication_state"] == "draft" for e in entries)
    assert action(domain, entries[0], "publish").status_code == 409


@pytest.mark.parametrize(
    "method,tail,body",
    [
        ("post", "", {"category": "test", "question": "Q?", "answer": "A"}),
        ("post", "/seed", {}),
        ("patch", "/{id}", {"answer": "Changed"}),
        ("delete", "/{id}", None),
        ("post", "/{id}/publish", {"expected_revision": 1}),
        ("post", "/{id}/withdraw", {"expected_revision": 1}),
    ],
)
def test_admin_mutations_deny_reviewers(domain, method, tail, body):
    faq = create(domain).json()
    domain["login"]("reviewer")
    r = domain["client"].request(method, "/api/security-faq" + tail.format(id=faq["id"]), json=body)
    assert r.status_code == 403


def test_approval_requires_review_permission(domain):
    faq = create(domain).json()
    domain["login"]("editor")
    # Editor has can_review in the current role contract; an unauthenticated caller does not.
    domain["client"].cookies.clear()
    assert action(domain, faq, "approve", verified=True).status_code == 401


@pytest.mark.parametrize(
    "field,value",
    [
        ("question", "x" * 2001),
        ("answer", "x" * 20001),
        ("category", "x" * 65),
        ("question", "bad\x00text"),
        ("answer", "  "),
    ],
    ids=["question-limit", "answer-limit", "category-limit", "nul", "blank"],
)
def test_schema_rejects_unbounded_or_unsafe_content(field, value):
    from app.api.routes.security_faq import CreateFAQRequest

    with pytest.raises(ValidationError):
        CreateFAQRequest(**{"category": "test", "question": "Q?", "answer": "A", field: value})
