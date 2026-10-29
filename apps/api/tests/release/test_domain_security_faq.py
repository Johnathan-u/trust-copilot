"""Reviewed FAQ lifecycle regressions, using synthetic data and exact row cleanup."""

import hashlib
import os
import secrets
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.session import sign_session
from app.models import ApiKey, AuditEvent, Document, EvidenceItem, User, Workspace, WorkspaceMember
from app.models.security_faq import SecurityFAQ, SecurityFAQRevision, SecurityFAQSource

ARCHIVES = (
    "tc17004_faq_state_archive",
    "tc17004_faq_history_archive",
    "tc17004_faq_source_archive",
)


@pytest.fixture
def domain(client, db_session):
    tables = (
        "workspaces",
        "users",
        "workspace_members",
        "security_faq",
        "security_faq_sources",
        "security_faq_revisions",
        "evidence_items",
        "documents",
        "audit_events",
        "idempotency_keys",
        "api_keys",
    )
    before = {t: db_session.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
    suffix = secrets.token_hex(8)
    ids = [600_000_000 + secrets.randbelow(100_000_000) for _ in range(2)]
    db_session.add_all(
        [Workspace(id=i, slug=f"faq-{suffix}-{i}", name="Synthetic FAQ") for i in ids]
    )
    actors = {}
    for role in ("admin", "reviewer", "editor", "no_access"):
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
    db_session.query(ApiKey).filter(ApiKey.workspace_id.in_(ids)).delete(synchronize_session=False)
    db_session.query(SecurityFAQ).filter(SecurityFAQ.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(EvidenceItem).filter(EvidenceItem.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(Document).filter(Document.workspace_id.in_(ids)).delete(
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
    assert all(
        db_session.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar() is None
        for t in ARCHIVES
    )


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
    domain["login"]("no_access")
    assert action(domain, faq, "approve", verified=True).status_code == 403
    domain["client"].cookies.clear()
    assert action(domain, faq, "approve", verified=True).status_code == 401


@pytest.mark.parametrize(
    "field,value",
    [
        ("question", "x" * 2001),
        ("answer", "x" * 20001),
        ("category", "x" * 65),
        ("question", "bad\x00text"),
        ("answer", "bad\ud800text"),
        ("answer", "  "),
    ],
    ids=["question-limit", "answer-limit", "category-limit", "nul", "surrogate", "blank"],
)
def test_schema_rejects_unbounded_or_unsafe_content(field, value):
    from app.api.routes.security_faq import CreateFAQRequest

    with pytest.raises(ValidationError):
        CreateFAQRequest(**{"category": "test", "question": "Q?", "answer": "A", field: value})


def publish(d):
    faq = create(d).json()
    assert action(d, faq, "approve", verified=True).status_code == 200
    response = action(d, faq, "publish")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("name", ["approve", "publish", "withdraw"])
def test_action_missing_and_foreign_are_equal_404(domain, name):
    rs = [
        action(domain, {"id": i, "revision": 1}, name, verified=True)
        for i in (2147483647, domain["foreign"])
    ]
    assert [r.status_code for r in rs] == [404, 404]
    assert rs[0].json() == rs[1].json()


@pytest.mark.parametrize("change", ["removed", "suspended", "demoted"])
@pytest.mark.parametrize(
    "name", ["create", "seed", "edit", "delete", "approve", "publish", "withdraw"]
)
def test_stale_admin_session_cannot_mutate_after_membership_change(domain, change, name):
    d = domain
    faq = create(d).json()
    member = (
        d["db"]
        .query(WorkspaceMember)
        .filter_by(workspace_id=d["ws"], user_id=d["actors"]["admin"])
        .one()
    )
    if change == "removed":
        d["db"].delete(member)
    elif change == "suspended":
        member.suspended = True
    else:
        member.role = "no_access"
    d["db"].commit()
    if name == "create":
        response = create(d)
    elif name == "seed":
        response = d["client"].post("/api/security-faq/seed")
    elif name == "edit":
        response = d["client"].patch(f"/api/security-faq/{faq['id']}", json={"answer": "Changed"})
    elif name == "delete":
        response = d["client"].delete(f"/api/security-faq/{faq['id']}")
    else:
        response = action(d, faq, name, verified=True)
    assert response.status_code == 403
    d["db"].expire_all()
    row = d["db"].get(SecurityFAQ, faq["id"])
    assert row.answer == faq["answer"] and row.revision == 1
    assert row.reviewed_at is None and row.published_at is None
    assert d["db"].query(SecurityFAQ).filter_by(workspace_id=d["ws"]).count() == 1


def test_api_key_cannot_supply_human_approval_identity(domain):
    d = domain
    faq = create(d).json()
    token = secrets.token_urlsafe(32)
    d["db"].add(
        ApiKey(
            workspace_id=d["ws"], key_hash=hashlib.sha256(token.encode()).hexdigest(), role="admin"
        )
    )
    d["db"].commit()
    d["client"].cookies.clear()
    response = d["client"].post(
        f"/api/security-faq/{faq['id']}/approve",
        json={"expected_revision": 1, "verified": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    d["db"].expire_all()
    assert d["db"].get(SecurityFAQ, faq["id"]).reviewed_by_user_id is None


def test_publication_requires_approved_evidence_and_current_review(domain):
    d = domain
    faq = create(d, source_evidence_ids=[]).json()
    assert action(d, faq, "approve", verified=True).status_code == 409
    faq = (
        d["client"]
        .patch(f"/api/security-faq/{faq['id']}", json={"source_evidence_ids": [d["evidence"]]})
        .json()
    )
    ev = d["db"].get(EvidenceItem, d["evidence"])
    ev.approval_status = "pending"
    d["db"].commit()
    assert action(d, faq, "approve", verified=True).status_code == 409
    ev.approval_status = "approved"
    d["db"].commit()
    assert action(d, faq, "approve", verified=False).status_code == 409
    assert action(d, faq, "approve", verified=True).status_code == 200
    ev.title = "Changed source after review"
    d["db"].commit()
    assert action(d, faq, "publish").status_code == 409
    assert action(d, faq, "approve", verified=True).status_code == 200
    assert action(d, faq, "publish").status_code == 200


@pytest.mark.parametrize("change", ["rejected", "edited", "deleted"])
def test_published_projection_is_read_only_and_hides_stale_support(domain, change):
    d = domain
    faq = publish(d)
    # A fresh SQLAlchemy session and ordinary GETs observe committed publication.
    d["db"].close()
    before = (
        d["db"]
        .execute(text("SELECT to_jsonb(f) FROM security_faq f WHERE id=:id"), {"id": faq["id"]})
        .scalar()
    )
    audit_count = d["db"].query(AuditEvent).filter_by(workspace_id=d["ws"]).count()
    assert [f["id"] for f in d["client"].get("/api/security-faq/published").json()["faqs"]] == [
        faq["id"]
    ]
    ev = d["db"].get(EvidenceItem, d["evidence"])
    if change == "deleted":
        d["db"].delete(ev)
    elif change == "rejected":
        ev.approval_status = "rejected"
    else:
        ev.title = "Evidence content changed"
    d["db"].commit()
    assert d["client"].get("/api/security-faq/published").json()["faqs"] == []
    after = (
        d["db"]
        .execute(text("SELECT to_jsonb(f) FROM security_faq f WHERE id=:id"), {"id": faq["id"]})
        .scalar()
    )
    assert after == before
    assert d["db"].query(AuditEvent).filter_by(workspace_id=d["ws"]).count() == audit_count


def test_withdraw_retry_and_delete_remove_public_content_and_children(domain):
    d = domain
    faq = publish(d)
    first = action(d, faq, "withdraw")
    assert first.status_code == 200
    assert action(d, faq, "withdraw").json() == first.json()
    assert d["client"].get("/api/security-faq/published").json()["faqs"] == []
    assert d["client"].delete(f"/api/security-faq/{faq['id']}").status_code == 200
    for model in (SecurityFAQRevision, SecurityFAQSource):
        assert d["db"].query(model).filter_by(faq_id=faq["id"]).count() == 0


def test_create_idempotency_replay_conflict_and_failed_source_cleanup(domain):
    d = domain
    body = {
        "category": "test",
        "question": "Question?",
        "answer": "Answer",
        "source_evidence_ids": [d["foreign_evidence"]],
    }
    headers = {"Idempotency-Key": "faq-retry"}
    assert d["client"].post("/api/security-faq", json=body, headers=headers).status_code == 404
    assert d["db"].query(SecurityFAQ).filter_by(workspace_id=d["ws"]).count() == 0
    assert d["db"].query(AuditEvent).filter_by(workspace_id=d["ws"]).count() == 0
    assert (
        d["db"]
        .execute(
            text("SELECT count(*) FROM idempotency_keys WHERE idempotency_key LIKE :p"),
            {"p": f"ws:{d['ws']}:faq:%"},
        )
        .scalar()
        == 0
    )
    body["source_evidence_ids"] = [d["evidence"]]
    first = d["client"].post("/api/security-faq", json=body, headers=headers)
    assert first.status_code == 200
    d["db"].close()
    assert d["client"].post("/api/security-faq", json=body, headers=headers).json() == first.json()
    body["answer"] = "Conflicting answer"
    assert d["client"].post("/api/security-faq", json=body, headers=headers).status_code == 409
    assert d["db"].query(SecurityFAQ).filter_by(workspace_id=d["ws"]).count() == 1
    assert d["db"].query(AuditEvent).filter_by(workspace_id=d["ws"]).count() == 1


def test_partial_database_failure_rolls_back_content_sources_history_and_audit(domain, monkeypatch):
    from app.services import security_faq_service as service

    d = domain
    faq = publish(d)
    counts = {
        m: d["db"].query(m).count() for m in (SecurityFAQRevision, SecurityFAQSource, AuditEvent)
    }
    original = service._audit

    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise IntegrityError("synthetic failure after writes", {}, Exception("rollback probe"))

    monkeypatch.setattr(service, "_audit", fail_after_audit)
    response = d["client"].patch(
        f"/api/security-faq/{faq['id']}",
        json={"answer": "Should roll back", "source_evidence_ids": [], "expected_revision": 1},
    )
    assert response.status_code == 409
    assert d["client"].get(f"/api/security-faq/{faq['id']}").json() == faq
    assert {m: d["db"].query(m).count() for m in counts} == counts


@pytest.mark.parametrize(
    "field,value",
    [
        ("question", "x" * 2001),
        ("answer", "x" * 20001),
        ("category", "x" * 65),
        ("publication_state", "invented"),
        ("revision", 0),
    ],
    ids=["question-limit", "answer-limit", "category-limit", "unknown-state", "invalid-revision"],
)
def test_database_rejects_invalid_content_and_lifecycle(domain, field, value):
    faq = create(domain).json()
    with pytest.raises(DBAPIError):
        domain["db"].execute(
            text(f"UPDATE security_faq SET {field}=:value WHERE id=:id"),
            {"value": value, "id": faq["id"]},
        )
        domain["db"].flush()
    domain["db"].rollback()


def test_database_rejects_foreign_source_and_parent_moves(domain):
    d = domain
    faq = create(d).json()
    statements = [
        (
            "INSERT INTO security_faq_sources VALUES (:id,:foreign)",
            {"id": faq["id"], "foreign": d["foreign_evidence"]},
        ),
        (
            "UPDATE security_faq SET workspace_id=:ws WHERE id=:id",
            {"id": faq["id"], "ws": d["foreign_ws"]},
        ),
        (
            "UPDATE evidence_items SET workspace_id=:ws WHERE id=:id",
            {"id": d["evidence"], "ws": d["foreign_ws"]},
        ),
        (
            "UPDATE security_faq_revisions SET workspace_id=:ws WHERE faq_id=:id",
            {"id": faq["id"], "ws": d["foreign_ws"]},
        ),
    ]
    for statement, params in statements:
        with pytest.raises(IntegrityError):
            d["db"].execute(text(statement), params)
            d["db"].flush()
        d["db"].rollback()


def test_concurrent_source_insert_and_parent_move_cannot_cross_workspaces(domain):
    d = domain
    faq = create(d, source_evidence_ids=[]).json()
    engine = d["db"].get_bind()
    d["db"].close()
    barrier = Barrier(2)

    def write(statement, params):
        with Session(engine) as db:
            db.execute(text("SET LOCAL lock_timeout='5s'"))
            barrier.wait(timeout=5)
            try:
                db.execute(text(statement), params)
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(
            write,
            "INSERT INTO security_faq_sources VALUES (:f,:e)",
            {"f": faq["id"], "e": d["evidence"]},
        )
        b = pool.submit(
            write,
            "UPDATE evidence_items SET workspace_id=:w WHERE id=:e",
            {"w": d["foreign_ws"], "e": d["evidence"]},
        )
        outcomes = [a.result(timeout=10), b.result(timeout=10)]
    assert sorted(outcomes) == [False, True]
    assert (
        d["db"]
        .execute(
            text(
                "SELECT count(*) FROM security_faq_sources s JOIN security_faq f ON f.id=s.faq_id JOIN evidence_items e ON e.id=s.evidence_item_id WHERE f.workspace_id <> e.workspace_id"
            )
        )
        .scalar()
        == 0
    )


def test_concurrent_source_inserts_cannot_exceed_database_limit(domain):
    d = domain
    evidence = [
        EvidenceItem(workspace_id=d["ws"], source_type="manual", title=f"Source {i}")
        for i in range(21)
    ]
    d["db"].add_all(evidence)
    d["db"].commit()
    ids = [e.id for e in evidence]
    faq = create(d, source_evidence_ids=ids[:19]).json()
    engine = d["db"].get_bind()
    d["db"].close()
    barrier = Barrier(2)

    def insert(eid):
        with Session(engine) as db:
            db.execute(text("SET LOCAL lock_timeout='5s'"))
            barrier.wait(timeout=5)
            try:
                db.add(SecurityFAQSource(faq_id=faq["id"], evidence_item_id=eid))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = [pool.submit(insert, i) for i in ids[19:]]
        assert sorted([a.result(timeout=10), b.result(timeout=10)]) == [False, True]
    assert d["db"].query(SecurityFAQSource).filter_by(faq_id=faq["id"]).count() == 20


def _script():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_faq_revision_is_on_single_head_chain():
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1
    assert "tc17004_faq_review" in {r.revision for r in script.walk_revisions("base", heads[0])}


def test_schema_model_indexes_foreign_keys_and_bounds_match(domain):
    inspector = inspect(domain["db"].get_bind())
    for model in (SecurityFAQ, SecurityFAQSource, SecurityFAQRevision):
        table = model.__table__
        actual_indexes = {
            i["name"]: tuple(i["column_names"]) for i in inspector.get_indexes(table.name)
        }
        for index in table.indexes:
            assert actual_indexes[index.name] == tuple(c.name for c in index.columns)
        actual_fks = {
            (
                tuple(f["constrained_columns"]),
                f["referred_table"],
                tuple(f["referred_columns"]),
                f["options"].get("ondelete"),
            )
            for f in inspector.get_foreign_keys(table.name)
        }
        for fk in table.foreign_key_constraints:
            assert (
                tuple(c.name for c in fk.columns),
                fk.referred_table.name,
                tuple(e.column.name for e in fk.elements),
                fk.ondelete,
            ) in actual_fks
        actual_columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        for column in table.columns:
            actual = actual_columns[column.name]
            assert actual["nullable"] == column.nullable
            assert getattr(actual["type"], "length", None) == getattr(column.type, "length", None)


def test_lossless_downgrade_roundtrip_and_rollback_edits_invalidate_review(domain):
    d = domain
    keep = publish(d)
    edit = publish(d)
    before_history = d["client"].get(f"/api/security-faq/{keep['id']}/revisions").json()
    d["db"].close()

    def alembic(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "TRUST_COPILOT_TESTING": "1", "PGOPTIONS": "-c lock_timeout=20000"},
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stdout[-1000:] + result.stderr[-2000:]

    try:
        alembic("downgrade", "tc17004_faq_review")
        alembic("downgrade", "-1")
        for table in ARCHIVES:
            assert d["db"].execute(text(f"SELECT count(*) FROM {table}")).scalar() >= 2
        assert (
            d["db"]
            .execute(
                text("SELECT reviewed_evidence_digest FROM tc17004_faq_state_archive WHERE id=:id"),
                {"id": keep["id"]},
            )
            .scalar()
        )
        d["db"].execute(
            text("UPDATE security_faq SET answer='Edited while rolled back' WHERE id=:id"),
            {"id": edit["id"]},
        )
        d["db"].commit()
        d["db"].close()
        alembic("upgrade", "head")
        assert d["client"].get(f"/api/security-faq/{keep['id']}").json() == keep
        assert d["client"].get(f"/api/security-faq/{keep['id']}/revisions").json() == before_history
        changed = d["client"].get(f"/api/security-faq/{edit['id']}").json()
        assert changed["answer"] == "Edited while rolled back"
        assert changed["revision"] == 2 and changed["publication_state"] == "draft"
        assert (
            changed["reviewed_at"] is None
            and changed["reviewed_by_user_id"] is None
            and changed["published_at"] is None
        )
        history = d["client"].get(f"/api/security-faq/{edit['id']}/revisions").json()["revisions"]
        assert [r["answer"] for r in history] == [edit["answer"], "Edited while rolled back"]
        legacy = d["db"].get(SecurityFAQ, d["foreign"])
        assert (
            legacy.revision is None
            and legacy.reviewed_at is None
            and legacy.publication_state is None
        )
        assert all(
            d["db"].execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar() is None
            for t in ARCHIVES
        )
    finally:
        d["db"].rollback()
        d["db"].close()
        alembic("upgrade", "head")


@pytest.mark.parametrize(
    "ids",
    [[True], [0], [-1], [2147483648], ["1"], list(range(1, 22))],
    ids=["bool", "zero", "negative", "overflow", "string", "too-many"],
)
def test_schema_rejects_unsafe_source_identifiers(ids):
    from app.api.routes.security_faq import CreateFAQRequest

    with pytest.raises(ValidationError):
        CreateFAQRequest(category="test", question="Q?", answer="A", source_evidence_ids=ids)


def test_template_edit_can_be_reviewed_without_inventing_prior_approval(domain):
    d = domain
    assert d["client"].post("/api/security-faq/seed").status_code == 200
    assert d["client"].post("/api/security-faq/seed").json() == {"created": 0}
    faq = d["client"].get("/api/security-faq").json()["faqs"][0]
    assert action(d, faq, "approve", verified=True).status_code == 409
    response = d["client"].patch(
        f"/api/security-faq/{faq['id']}",
        json={
            "expected_revision": 1,
            "answer": "Synthetic evidence-backed answer",
            "source_evidence_ids": [d["evidence"]],
        },
    )
    assert response.status_code == 200
    faq = response.json()
    assert faq["synthetic"] is True and faq["reviewed_at"] is None
    approved = action(d, faq, "approve", verified=True)
    assert approved.status_code == 200 and approved.json()["synthetic"] is False
    assert action(d, faq, "publish").status_code == 200
    assert [f["id"] for f in d["client"].get("/api/security-faq/published").json()["faqs"]] == [
        faq["id"]
    ]


def test_empty_gets_do_not_seed_templates_or_write_audit(domain):
    d = domain
    assert d["client"].get("/api/security-faq").json() == {"faqs": []}
    assert d["client"].get("/api/security-faq/categories").json() == {"categories": []}
    assert d["client"].get("/api/security-faq/published").json() == {"faqs": []}
    assert d["db"].query(SecurityFAQ).filter_by(workspace_id=d["ws"]).count() == 0
    assert d["db"].query(AuditEvent).filter_by(workspace_id=d["ws"]).count() == 0


def test_idempotency_claim_commit_cannot_bypass_a_concurrent_demotion(domain, monkeypatch):
    from app.core import idempotency

    d = domain
    claim = idempotency.claim

    def demote_after_claim(db, *args, **kwargs):
        owner = claim(db, *args, **kwargs)
        # Use the committed boundary created by the real lease claim.
        with Session(db.get_bind()) as other:
            member = (
                other.query(WorkspaceMember)
                .filter_by(workspace_id=d["ws"], user_id=d["actors"]["admin"])
                .one()
            )
            member.role = "reviewer"
            other.commit()
        return owner

    monkeypatch.setattr(idempotency, "claim", demote_after_claim)
    response = d["client"].post(
        "/api/security-faq",
        json={"category": "test", "question": "Q?", "answer": "A"},
        headers={"Idempotency-Key": "demotion-probe"},
    )
    assert response.status_code == 403
    assert d["db"].query(SecurityFAQ).filter_by(workspace_id=d["ws"]).count() == 0
    assert (
        d["db"]
        .execute(
            text("SELECT count(*) FROM idempotency_keys WHERE idempotency_key LIKE :p"),
            {"p": f"ws:{d['ws']}:faq:%"},
        )
        .scalar()
        == 0
    )


def test_document_replacement_invalidates_reviewed_evidence(domain):
    d = domain
    document = Document(
        workspace_id=d["ws"], storage_key=f"synthetic/{d['suffix']}/v1.txt", filename="Policy.txt"
    )
    d["db"].add(document)
    d["db"].flush()
    d["db"].get(EvidenceItem, d["evidence"]).document_id = document.id
    d["db"].commit()
    faq = publish(d)
    document.storage_key = f"synthetic/{d['suffix']}/v2.txt"
    d["db"].commit()
    assert d["client"].get("/api/security-faq/published").json()["faqs"] == []
    assert action(d, faq, "publish").status_code == 409
    assert action(d, faq, "approve", verified=True).status_code == 200
    assert action(d, faq, "publish").status_code == 200
