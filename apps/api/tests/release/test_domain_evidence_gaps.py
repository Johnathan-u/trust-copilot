"""TC-21-013 evidence gap ownership and resolution.

Runs on PostgreSQL. Labels are synthetic, not framework text.
Notification delivery is stubbed.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.api.routes import evidence_gaps as gaps_mod
from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import (
    Answer,
    Chunk,
    ControlEvidenceLink,
    CustomRole,
    Document,
    EvidenceGap,
    EvidenceItem,
    Question,
    Questionnaire,
    User,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
from app.models import CONTROL_CHECK
from app.models.evidence_gap import CONTROL_CHECK_CLOSE_REASON

SLUG = "tc21013"
ADMIN_EMAIL = "tc21013-admin@trust.local"
EDITOR_EMAIL = "tc21013-editor@trust.local"
REVIEWER_EMAIL = "tc21013-reviewer@trust.local"
NO_REVIEW_EMAIL = "tc21013-noreview@trust.local"
OTHER_EMAIL = "tc21013-other@trust.local"
ADMIN_PASSWORD = "test-a"
EDITOR_PASSWORD = "test-e"
REVIEWER_PASSWORD = "test-r"
NO_REVIEW_PASSWORD = "test-n"
OTHER_PASSWORD = "test-o"
NO_REVIEW_ROLE = "tc21013-noreview"
_COUNTED = (
    "control_evidence_links",
    "chunks",
    "answers",
    "questions",
    "questionnaires",
    "evidence_items",
    "documents",
    "evidence_gaps",
    "workspace_controls",
    "custom_roles",
    "in_app_notifications",
    "idempotency_keys",
    "audit_events",
    "user_sessions",
    "workspace_members",
    "users",
    "workspaces",
)


def _db() -> Session:
    return SessionLocal()


def _sync_sequence(session: Session, table: str) -> None:
    session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM " + table + "))"
        ),
        {"table": table},
    )


def _reset_login_limit() -> None:
    from app.core import rate_limit

    with rate_limit._lock:
        rate_limit._store.clear()


def _counts() -> dict[str, int]:
    session = _db()
    try:
        return {
            name: int(session.execute(text(f"SELECT count(*) FROM {name}")).scalar() or 0)
            for name in _COUNTED
        }
    finally:
        session.close()


def _ids() -> dict[str, set[int]]:
    session = _db()
    try:
        found = {}
        for name in _COUNTED:
            rows = session.execute(text(f"SELECT id FROM {name}")).fetchall()
            found[name] = {row[0] for row in rows}
        return found
    finally:
        session.close()


def _delete_created(before: dict[str, set[int]]) -> None:
    session = _db()
    try:
        for name in _COUNTED:
            current = {row[0] for row in session.execute(text(f"SELECT id FROM {name}")).fetchall()}
            created = sorted(current - before[name])
            if not created:
                continue
            statement = text(f"DELETE FROM {name} WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            session.execute(statement, {"ids": created})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(autouse=True)
def restored_rows():
    _reset_login_limit()
    before_counts = _counts()
    before_ids = _ids()
    try:
        yield
    finally:
        _delete_created(before_ids)
        after_counts = _counts()
        assert after_counts == before_counts, {"before": before_counts, "after": after_counts}


def _actors() -> dict[str, int]:
    session = _db()
    try:
        workspace = session.query(Workspace).filter(Workspace.slug == SLUG).one_or_none()
        if workspace is None:
            _sync_sequence(session, "workspaces")
            workspace = Workspace(name="TC-21-013", slug=SLUG)
            session.add(workspace)
            session.flush()
        other = session.query(Workspace).filter(Workspace.slug == SLUG + "-other").one_or_none()
        if other is None:
            _sync_sequence(session, "workspaces")
            other = Workspace(name="TC-21-013 other", slug=SLUG + "-other")
            session.add(other)
            session.flush()
        role = (
            session.query(CustomRole)
            .filter(CustomRole.workspace_id == workspace.id, CustomRole.name == NO_REVIEW_ROLE)
            .one_or_none()
        )
        if role is None:
            _sync_sequence(session, "custom_roles")
            session.add(
                CustomRole(
                    workspace_id=workspace.id,
                    name=NO_REVIEW_ROLE,
                    description="Synthetic role with no review permission",
                    can_edit=False,
                    can_review=False,
                    can_export=False,
                    can_admin=False,
                )
            )

        def member(email: str, password: str, role_name: str, ws: Workspace) -> User:
            user = session.query(User).filter(User.email == email).one_or_none()
            if user is None:
                _sync_sequence(session, "users")
                user = User(email=email, password_hash=hash_password(password), display_name=email)
                session.add(user)
                session.flush()
            row = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.workspace_id == ws.id,
                )
                .one_or_none()
            )
            if row is None:
                session.add(
                    WorkspaceMember(
                        workspace_id=ws.id, user_id=user.id, role=role_name, suspended=False
                    )
                )
            else:
                row.role = role_name
                row.suspended = False
            return user

        admin = member(ADMIN_EMAIL, ADMIN_PASSWORD, "admin", workspace)
        member(EDITOR_EMAIL, EDITOR_PASSWORD, "editor", workspace)
        member(REVIEWER_EMAIL, REVIEWER_PASSWORD, "reviewer", workspace)
        member(NO_REVIEW_EMAIL, NO_REVIEW_PASSWORD, NO_REVIEW_ROLE, workspace)
        member(OTHER_EMAIL, OTHER_PASSWORD, "admin", other)
        session.commit()
        return {
            "workspace_id": workspace.id,
            "other_workspace_id": other.id,
            "admin_id": admin.id,
        }
    finally:
        session.close()


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _control(workspace_id: int, name: str, owner_user_id: int | None = None) -> int:
    session = _db()
    try:
        _sync_sequence(session, "workspace_controls")
        row = WorkspaceControl(
            workspace_id=workspace_id,
            status="not_implemented",
            custom_name=name,
            owner_user_id=owner_user_id,
        )
        session.add(row)
        session.commit()
        return row.id
    finally:
        session.close()


def _evidence(workspace_id: int, *, approval: str) -> int:
    session = _db()
    try:
        _sync_sequence(session, "documents")
        doc = Document(
            workspace_id=workspace_id,
            storage_key=f"tc21013/{uuid.uuid4().hex}",
            filename="synthetic.txt",
            status="uploaded",
        )
        session.add(doc)
        session.flush()
        _sync_sequence(session, "evidence_items")
        row = EvidenceItem(
            workspace_id=workspace_id,
            document_id=doc.id,
            source_type="document",
            title="Synthetic evidence",
            approval_status=approval,
        )
        session.add(row)
        session.commit()
        return row.id, doc.id
    finally:
        session.close()


def _link(control_id: int, evidence_id: int) -> None:
    session = _db()
    try:
        session.add(
            ControlEvidenceLink(control_id=control_id, evidence_id=evidence_id, verified=False)
        )
        session.commit()
    finally:
        session.close()


def _gap(workspace_id: int, **kwargs) -> int:
    session = _db()
    try:
        _sync_sequence(session, "evidence_gaps")
        fields = {"evidence_refs": "[]"}
        fields.update(kwargs)
        row = EvidenceGap(workspace_id=workspace_id, status="open", **fields)
        session.add(row)
        session.commit()
        return row.id
    finally:
        session.close()


def _row(gap_id: int) -> tuple:
    session = _db()
    try:
        return tuple(
            session.execute(
                text(
                    "SELECT status, close_reason, evidence_refs, evaluation_state, rule_code "
                    "FROM evidence_gaps WHERE id = :id"
                ),
                {"id": gap_id},
            ).one()
        )
    finally:
        session.close()


def _unchanged(gap_id: int, stored: tuple, before_audit: int, before_keys: int) -> None:
    assert _row(gap_id) == stored
    assert _counts()["audit_events"] == before_audit
    assert _counts()["idempotency_keys"] == before_keys


def test_create_decision_and_resolve_permissions(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Denied {uuid.uuid4().hex[:8]}")
    gap_id = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=control_id)
    approved, _doc = _evidence(actors["workspace_id"], approval="approved")
    _link(control_id, approved)
    stored = _row(gap_id)
    calls = (
        ("POST", "/api/evidence-gaps", {"gap_type": CONTROL_CHECK, "control_id": control_id}),
        ("POST", f"/api/evidence-gaps/{gap_id}/decision", {"status": "accepted"}),
        ("POST", f"/api/evidence-gaps/{gap_id}/resolve", {"evidence_id": approved}),
    )
    client.cookies.clear()
    before_audit = _counts()["audit_events"]
    before_keys = _counts()["idempotency_keys"]
    for method, path, body in calls:
        response = client.post(path, json=body, headers={"Idempotency-Key": "anon-key"})
        assert response.status_code == 401, (path, response.text)
        _unchanged(gap_id, stored, before_audit, before_keys)
    _login(client, NO_REVIEW_EMAIL, NO_REVIEW_PASSWORD)
    before_audit = _counts()["audit_events"]
    before_keys = _counts()["idempotency_keys"]
    for path, body in (
        ("/api/evidence-gaps", {"gap_type": CONTROL_CHECK, "control_id": control_id}),
        (f"/api/evidence-gaps/{gap_id}/decision", {"status": "accepted"}),
        (f"/api/evidence-gaps/{gap_id}/resolve", {"evidence_id": approved}),
    ):
        response = client.post(path, json=body, headers={"Idempotency-Key": "noreview-key"})
        assert response.status_code == 403, (path, response.text)
        assert response.json()["detail"] == "Insufficient permissions"
        _unchanged(gap_id, stored, before_audit, before_keys)
    for role, email, password in (
        ("reviewer", REVIEWER_EMAIL, REVIEWER_PASSWORD),
        ("editor", EDITOR_EMAIL, EDITOR_PASSWORD),
    ):
        _login(client, email, password)
        before_audit = _counts()["audit_events"]
        before_keys = _counts()["idempotency_keys"]
        denied = client.post(
            f"/api/evidence-gaps/{gap_id}/decision",
            json={"status": "dismissed"},
            headers={"Idempotency-Key": f"deny-{role}"},
        )
        assert denied.status_code == 403, (role, denied.text)
        _unchanged(gap_id, stored, before_audit, before_keys)
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    created = client.post(
        "/api/evidence-gaps",
        json={"gap_type": "missing_evidence", "question_id": None, "control_id": control_id},
    )
    # control create is review; a second type still opens when none exists for that type
    assert created.status_code in (200, 201), created.text
    resolved = client.post(f"/api/evidence-gaps/{gap_id}/resolve", json={"evidence_id": approved})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    other = _gap(actors["workspace_id"], gap_type="missing_evidence", control_id=control_id)
    accepted = client.post(f"/api/evidence-gaps/{other}/decision", json={"status": "accepted"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"


def test_denial_at_each_permission_level(client):
    _actors()
    client.cookies.clear()
    assert client.get("/api/evidence-gaps").status_code == 401
    for role, email, password, code in (
        ("noreview", NO_REVIEW_EMAIL, NO_REVIEW_PASSWORD, 403),
        ("reviewer", REVIEWER_EMAIL, REVIEWER_PASSWORD, 200),
        ("editor", EDITOR_EMAIL, EDITOR_PASSWORD, 200),
        ("admin", ADMIN_EMAIL, ADMIN_PASSWORD, 200),
    ):
        _login(client, email, password)
        before = _counts()
        listed = client.get("/api/evidence-gaps")
        assert listed.status_code == code, (role, listed.text)
        assert _counts() == before
        if code == 403:
            assert listed.json()["detail"] == "Insufficient permissions"


def test_missing_and_foreign_ids_share_the_404(client):
    actors = _actors()
    own_control = _control(actors["workspace_id"], f"Own {uuid.uuid4().hex[:8]}")
    foreign_control = _control(actors["other_workspace_id"], f"Foreign {uuid.uuid4().hex[:8]}")
    own_gap = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=own_control)
    foreign_gap = _gap(
        actors["other_workspace_id"], gap_type=CONTROL_CHECK, control_id=foreign_control
    )
    session = _db()
    try:
        _sync_sequence(session, "questionnaires")
        own_qnr = Questionnaire(
            workspace_id=actors["workspace_id"], filename="own.txt", status="parsed"
        )
        other_qnr = Questionnaire(
            workspace_id=actors["other_workspace_id"], filename="other.txt", status="parsed"
        )
        session.add(own_qnr)
        session.add(other_qnr)
        session.flush()
        _sync_sequence(session, "questions")
        own_question = Question(questionnaire_id=own_qnr.id, text="Synthetic own question")
        foreign_question = Question(questionnaire_id=other_qnr.id, text="Synthetic other question")
        session.add(own_question)
        session.add(foreign_question)
        session.commit()
        own_question_id = own_question.id
        foreign_question_id = foreign_question.id
    finally:
        session.close()
    own_evidence, _doc = _evidence(actors["workspace_id"], approval="approved")
    foreign_evidence, _other_doc = _evidence(actors["other_workspace_id"], approval="approved")
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

    def same(missing_response, foreign_response, detail: str):
        assert missing_response.status_code == 404, missing_response.text
        assert foreign_response.status_code == 404, foreign_response.text
        assert missing_response.json() == foreign_response.json()
        assert missing_response.json() == {"detail": detail}

    same(
        client.get("/api/evidence-gaps/999999991"),
        client.get(f"/api/evidence-gaps/{foreign_gap}"),
        "Gap not found",
    )
    same(
        client.post(
            "/api/evidence-gaps", json={"gap_type": CONTROL_CHECK, "control_id": 999999991}
        ),
        client.post(
            "/api/evidence-gaps",
            json={"gap_type": CONTROL_CHECK, "control_id": foreign_control},
        ),
        "Control not found",
    )
    same(
        client.post(
            "/api/evidence-gaps", json={"gap_type": "missing_evidence", "question_id": 999999991}
        ),
        client.post(
            "/api/evidence-gaps",
            json={"gap_type": "missing_evidence", "question_id": foreign_question_id},
        ),
        "Question not found",
    )
    same(
        client.post(f"/api/evidence-gaps/{own_gap}/resolve", json={"evidence_id": 999999991}),
        client.post(
            f"/api/evidence-gaps/{own_gap}/resolve", json={"evidence_id": foreign_evidence}
        ),
        "Evidence not found",
    )
    assert str(foreign_evidence) not in client.get(f"/api/evidence-gaps/{own_gap}").text
    assert own_question_id


def test_resolve_requires_eligible_backing_evidence(client):
    actors = _actors()
    control_id = _control(
        actors["workspace_id"], f"Resolve {uuid.uuid4().hex[:8]}", actors["admin_id"]
    )
    gap_id = _gap(
        actors["workspace_id"],
        gap_type=CONTROL_CHECK,
        control_id=control_id,
        evaluation_state="gap",
        rule_code="no_evidence",
        created_at=datetime.now(timezone.utc) - timedelta(days=20),
    )
    pending, _pending_doc = _evidence(actors["workspace_id"], approval="pending")
    _link(control_id, pending)
    approved, _approved_doc = _evidence(actors["workspace_id"], approval="approved")
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    before = _counts()
    listed = client.get(f"/api/evidence-gaps/{gap_id}")
    assert listed.status_code == 200, listed.text
    assert _counts() == before
    body = listed.json()
    assert body["schema_version"] == gaps_mod.SCHEMA_VERSION
    assert body["owner_user_id"] == actors["admin_id"]
    assert body["owner_missing"] is False
    assert body["age_days"] >= 14
    assert body["priority"] == "high"
    again = client.get(f"/api/evidence-gaps/{gap_id}")
    assert again.json()["age_days"] == body["age_days"]
    assert again.json()["priority"] == body["priority"]
    refused = client.post(f"/api/evidence-gaps/{gap_id}/resolve", json={"evidence_id": pending})
    assert refused.status_code == 400, refused.text
    unlinked = client.post(f"/api/evidence-gaps/{gap_id}/resolve", json={"evidence_id": approved})
    assert unlinked.status_code == 400, unlinked.text
    _link(control_id, approved)
    key = f"resolve-{uuid.uuid4().hex}"
    with patch("app.api.routes.evidence_gaps.notify_admins") as notify:
        notify.side_effect = RuntimeError("delivery failed")
        failed = client.post(
            f"/api/evidence-gaps/{gap_id}/resolve",
            json={"evidence_id": approved},
            headers={"Idempotency-Key": key},
        )
    assert failed.status_code == 200, failed.text
    assert failed.json()["resolved"] is True
    assert failed.json()["notification_error"] == "delivery_failed"
    assert str(gap_id) not in notify.call_args.args[3]
    assert CONTROL_CHECK in notify.call_args.args[3]
    assert failed.json()["close_reason"] == CONTROL_CHECK_CLOSE_REASON
    assert str(approved) in failed.text
    retried = client.post(
        f"/api/evidence-gaps/{gap_id}/resolve",
        json={"evidence_id": approved},
        headers={"Idempotency-Key": key},
    )
    assert retried.status_code == 200
    assert retried.json() == failed.json()
    session = _db()
    try:
        stored = session.execute(
            text("SELECT status, close_reason FROM evidence_gaps WHERE id = :id"),
            {"id": gap_id},
        ).one()
    finally:
        session.close()
    assert stored.status == "resolved"
    assert stored.close_reason == CONTROL_CHECK_CLOSE_REASON
    session = _db()
    try:
        audit = session.execute(
            text(
                "SELECT user_id FROM audit_events "
                "WHERE action = 'gap_resolved' AND resource_id = :id"
            ),
            {"id": str(gap_id)},
        ).one()
    finally:
        session.close()
    assert audit.user_id == actors["admin_id"]


def test_duplicate_open_gap_is_explained_and_not_created(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Dup {uuid.uuid4().hex[:8]}")
    first = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=control_id)
    second = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=control_id)
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    listed = client.get("/api/evidence-gaps")
    assert listed.status_code == 200, listed.text
    rows = [item for item in listed.json()["gaps"] if item["control_id"] == control_id]
    assert rows[0]["duplicate"]["duplicate"] is True
    assert rows[0]["duplicate"]["open_ids"] == sorted([first, second])
    assert rows[0]["duplicate"]["canonical_id"] == min(first, second)
    before = _counts()["evidence_gaps"]
    ensured = client.post(
        "/api/evidence-gaps",
        json={"gap_type": CONTROL_CHECK, "control_id": control_id},
    )
    assert ensured.status_code == 200, ensured.text
    assert ensured.json()["id"] == min(first, second)
    assert ensured.json()["created"] is False
    assert _counts()["evidence_gaps"] == before


def test_reviewer_decision_is_not_overwritten_or_reopened(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Decided {uuid.uuid4().hex[:8]}")
    gap_id = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=control_id)
    approved, _doc = _evidence(actors["workspace_id"], approval="approved")
    _link(control_id, approved)
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    decided = client.post(f"/api/evidence-gaps/{gap_id}/decision", json={"status": "accepted"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "accepted"
    session = _db()
    try:
        audit = session.execute(
            text(
                "SELECT action, user_id FROM audit_events "
                "WHERE action = 'gap_decided' AND resource_id = :id"
            ),
            {"id": str(gap_id)},
        ).one()
    finally:
        session.close()
    assert audit.action == "gap_decided"
    assert audit.user_id == actors["admin_id"]
    kept = client.post(f"/api/evidence-gaps/{gap_id}/decision", json={"status": "dismissed"})
    assert kept.status_code == 409, kept.text
    assert _row(gap_id)[0] == "accepted"
    resolved = client.post(f"/api/evidence-gaps/{gap_id}/resolve", json={"evidence_id": approved})
    assert resolved.status_code == 409, resolved.text
    assert _row(gap_id)[0] == "accepted"
    before = _counts()["evidence_gaps"]
    ensured = client.post(
        "/api/evidence-gaps",
        json={"gap_type": CONTROL_CHECK, "control_id": control_id},
    )
    assert ensured.status_code == 200, ensured.text
    assert ensured.json()["status"] == "accepted"
    assert ensured.json()["created"] is False
    assert _counts()["evidence_gaps"] == before


def test_foreign_evidence_id_is_omitted_from_the_response_and_the_row(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Leak {uuid.uuid4().hex[:8]}")
    foreign_evidence, _doc = _evidence(actors["other_workspace_id"], approval="approved")
    marker = 88021013
    session = _db()
    try:
        session.execute(
            text("UPDATE evidence_items SET id = :marker WHERE id = :old"),
            {"marker": marker, "old": foreign_evidence},
        )
        session.commit()
    finally:
        session.close()
    gap_id = _gap(
        actors["workspace_id"],
        gap_type=CONTROL_CHECK,
        control_id=control_id,
        evidence_refs=json.dumps([marker]),
    )
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    listed = client.get(f"/api/evidence-gaps/{gap_id}")
    assert listed.status_code == 200, listed.text
    assert str(marker) not in listed.text
    decided = client.post(f"/api/evidence-gaps/{gap_id}/decision", json={"status": "dismissed"})
    assert decided.status_code == 200, decided.text
    assert str(marker) not in decided.text
    session = _db()
    try:
        stored = session.execute(
            text("SELECT evidence_refs FROM evidence_gaps WHERE id = :id"), {"id": gap_id}
        ).scalar()
    finally:
        session.close()
    assert str(marker) not in (stored or "")


def test_decided_row_is_not_rewritten_by_reads_or_retry(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Frozen {uuid.uuid4().hex[:8]}")
    foreign_evidence, _doc = _evidence(actors["other_workspace_id"], approval="approved")
    marker = 88021014
    stamp = datetime(2024, 1, 2, 3, 4, 5)
    session = _db()
    try:
        session.execute(
            text("UPDATE evidence_items SET id = :marker WHERE id = :old"),
            {"marker": marker, "old": foreign_evidence},
        )
        _sync_sequence(session, "evidence_gaps")
        gap_id = session.execute(
            text(
                "INSERT INTO evidence_gaps ("
                "workspace_id, gap_type, reason, status, created_at, updated_at, "
                "control_id, evidence_refs"
                ") VALUES ("
                ":ws, :gap_type, 'kept', 'accepted', :stamp, :stamp, :control, :refs"
                ") RETURNING id"
            ),
            {
                "ws": actors["workspace_id"],
                "stamp": stamp,
                "control": control_id,
                "gap_type": CONTROL_CHECK,
                "refs": json.dumps([marker]),
            },
        ).scalar()
        session.commit()
    finally:
        session.close()
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    listed = client.get("/api/evidence-gaps")
    one = client.get(f"/api/evidence-gaps/{gap_id}")
    assert listed.status_code == 200 and one.status_code == 200
    assert str(marker) not in listed.text
    assert str(marker) not in one.text
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    retried = client.post(f"/api/evidence-gaps/{gap_id}/decision", json={"status": "dismissed"})
    assert retried.status_code == 409, retried.text
    session = _db()
    try:
        stored = session.execute(
            text("SELECT evidence_refs, updated_at, status FROM evidence_gaps WHERE id = :id"),
            {"id": gap_id},
        ).one()
    finally:
        session.close()
    assert stored.status == "accepted"
    assert str(marker) in (stored.evidence_refs or "")
    assert stored.updated_at.replace(tzinfo=None) == stamp


def test_question_gaps_share_one_open_row_and_survive_a_conflict(client):
    actors = _actors()
    session = _db()
    try:
        _sync_sequence(session, "questionnaires")
        qnr = Questionnaire(
            workspace_id=actors["workspace_id"], filename="race.txt", status="parsed"
        )
        session.add(qnr)
        session.flush()
        _sync_sequence(session, "questions")
        question = Question(questionnaire_id=qnr.id, text="Synthetic race question")
        session.add(question)
        session.commit()
        question_id = question.id
        questionnaire_id = qnr.id
    finally:
        session.close()
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    first = client.post(
        "/api/evidence-gaps",
        json={"gap_type": "missing_evidence", "question_id": question_id, "reason": "Need a file"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["questionnaire_id"] == questionnaire_id
    second = client.post(
        "/api/evidence-gaps",
        json={"gap_type": "other_gap", "question_id": question_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["created"] is False
    real_matches = gaps_mod._matching_gaps
    seen = {"n": 0}

    def hide_the_open_row(*args, **kwargs):
        rows = real_matches(*args, **kwargs)
        seen["n"] += 1
        if seen["n"] == 1:
            return [row for row in rows if row.status != "open"]
        return rows

    with patch("app.api.routes.evidence_gaps._matching_gaps", side_effect=hide_the_open_row):
        conflict = client.post(
            "/api/evidence-gaps",
            json={"gap_type": "other_gap", "question_id": question_id},
        )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["id"] == first.json()["id"]
    assert conflict.json()["created"] is False
    assert seen["n"] >= 2


def test_concurrent_question_creates_leave_one_open_row(client):
    import threading

    from fastapi.testclient import TestClient

    from app.main import app
    from tests.conftest import TEST_HEADERS, TEST_ORIGIN

    actors = _actors()
    session = _db()
    try:
        _sync_sequence(session, "questionnaires")
        qnr = Questionnaire(
            workspace_id=actors["workspace_id"], filename="conc.txt", status="parsed"
        )
        session.add(qnr)
        session.flush()
        _sync_sequence(session, "questions")
        question = Question(questionnaire_id=qnr.id, text="Synthetic concurrent question")
        session.add(question)
        session.commit()
        question_id = question.id
    finally:
        session.close()
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    token = client.cookies.get("tc_session")
    barrier = threading.Barrier(2)
    results: list[int] = []

    def post_one() -> None:
        local = TestClient(app, base_url=TEST_ORIGIN, headers=TEST_HEADERS)
        local.cookies.set("tc_session", token)
        barrier.wait()
        response = local.post(
            "/api/evidence-gaps",
            json={"gap_type": "missing_evidence", "question_id": question_id},
        )
        results.append(response.status_code)

    threads = [threading.Thread(target=post_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [200, 201]
    session = _db()
    try:
        count = session.execute(
            text(
                "SELECT count(*) FROM evidence_gaps " "WHERE question_id = :id AND status = 'open'"
            ),
            {"id": question_id},
        ).scalar()
    finally:
        session.close()
    assert count == 1


def _lock_wait_visible() -> bool:
    """True when another backend is blocked on a row or advisory lock."""
    session = _db()
    try:
        row = session.execute(
            text(
                """
                SELECT 1
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid()
                  AND wait_event_type = 'Lock'
                  AND wait_event IN ('advisory', 'transactionid', 'tuple')
                UNION ALL
                SELECT 1
                FROM pg_locks
                WHERE NOT granted
                  AND locktype IN ('advisory', 'transactionid', 'tuple')
                LIMIT 1
                """
            )
        ).first()
        return row is not None
    finally:
        session.close()


def _wait_for_lock(timeout: float = 5.0) -> bool:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _lock_wait_visible():
            return True
        time.sleep(0.05)
    return False


def test_decision_and_resolve_race_for_one_open_gap(client):
    import threading

    from fastapi.testclient import TestClient

    from app.main import app
    from tests.conftest import TEST_HEADERS, TEST_ORIGIN

    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Race {uuid.uuid4().hex[:8]}")
    gap_id = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=control_id)
    evidence_id, _doc = _evidence(actors["workspace_id"], approval="approved")
    _link(control_id, evidence_id)
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    token = client.cookies.get("tc_session")
    holding = threading.Event()
    release = threading.Event()
    outcomes: list[tuple[str, int, dict]] = []
    real_update = gaps_mod._update_open_gap

    def update_and_hold(db, gap_id_arg, workspace_id, values):
        won = real_update(db, gap_id_arg, workspace_id, values)
        if won and not holding.is_set():
            holding.set()
            assert release.wait(timeout=8), "winner was not released"
        return won

    def post(path: str, body: dict, raw_key: str) -> None:
        local = TestClient(app, base_url=TEST_ORIGIN, headers=TEST_HEADERS)
        local.cookies.set("tc_session", token)
        response = local.post(path, json=body, headers={"Idempotency-Key": raw_key})
        outcomes.append((raw_key, response.status_code, response.json()))

    with patch("app.api.routes.evidence_gaps._update_open_gap", side_effect=update_and_hold):
        decision = threading.Thread(
            target=post,
            args=(
                f"/api/evidence-gaps/{gap_id}/decision",
                {"status": "accepted"},
                "race-decide",
            ),
        )
        decision.start()
        assert holding.wait(timeout=8), "decision never locked the open row"
        resolve = threading.Thread(
            target=post,
            args=(
                f"/api/evidence-gaps/{gap_id}/resolve",
                {"evidence_id": evidence_id},
                "race-resolve",
            ),
        )
        resolve.start()
        assert _wait_for_lock(), "resolve did not wait on the open-row lock"
        release.set()
        decision.join(timeout=8)
        resolve.join(timeout=8)
    assert sorted(item[1] for item in outcomes) == [200, 409], outcomes
    winner = next(item for item in outcomes if item[1] == 200)
    loser = next(item for item in outcomes if item[1] == 409)
    if winner[2]["status"] == "resolved":
        assert loser[2]["detail"] == "already resolved"
    else:
        assert loser[2]["detail"] == "Gap is not open"
    session = _db()
    try:
        status = session.execute(
            text("SELECT status FROM evidence_gaps WHERE id = :id"),
            {"id": gap_id},
        ).scalar()
        audits = session.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE resource_type = 'evidence_gap' AND resource_id = :id "
                "AND action IN ('gap_decided', 'gap_resolved')"
            ),
            {"id": str(gap_id)},
        ).scalar()
        loser_keys = session.execute(
            text("SELECT count(*) FROM idempotency_keys WHERE idempotency_key LIKE :needle"),
            {"needle": f"%:{loser[0]}"},
        ).scalar()
        winner_keys = session.execute(
            text("SELECT count(*) FROM idempotency_keys WHERE idempotency_key LIKE :needle"),
            {"needle": f"%:{winner[0]}"},
        ).scalar()
    finally:
        session.close()
    assert status == winner[2]["status"]
    assert audits == 1
    assert loser_keys == 0
    assert winner_keys == 1


def test_scan_and_manual_create_leave_one_open_control_gap(client):
    import threading

    from fastapi.testclient import TestClient

    from app.api.routes import compliance_gaps as scan_mod
    from app.main import app
    from tests.conftest import TEST_HEADERS, TEST_ORIGIN

    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Scan race {uuid.uuid4().hex[:8]}")
    scan_mod._last_gap_notify.pop(actors["workspace_id"], None)
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    token = client.cookies.get("tc_session")
    holding = threading.Event()
    release = threading.Event()
    codes: list[int] = []
    real_lock = scan_mod._lock_control_gap_writes

    def lock_and_hold(db, locked_control_id: int) -> None:
        real_lock(db, locked_control_id)
        if locked_control_id == control_id and not holding.is_set():
            holding.set()
            assert release.wait(timeout=8), "scan was not released"

    def call(path: str, body: dict | None) -> None:
        local = TestClient(app, base_url=TEST_ORIGIN, headers=TEST_HEADERS)
        local.cookies.set("tc_session", token)
        if body is None:
            response = local.post(path)
        else:
            response = local.post(path, json=body)
        codes.append(response.status_code)

    with patch(
        "app.api.routes.compliance_gaps._lock_control_gap_writes",
        side_effect=lock_and_hold,
    ):
        scan = threading.Thread(target=call, args=("/api/compliance/gaps/scan-and-notify", None))
        scan.start()
        assert holding.wait(timeout=8), "scan never took the control lock"
        create = threading.Thread(
            target=call,
            args=(
                "/api/evidence-gaps",
                {"gap_type": CONTROL_CHECK, "control_id": control_id},
            ),
        )
        create.start()
        assert _wait_for_lock(), "create did not wait on the control advisory lock"
        release.set()
        scan.join(timeout=8)
        create.join(timeout=8)
    assert sorted(codes) in ([200, 200], [200, 201]), codes
    session = _db()
    try:
        count = session.execute(
            text(
                "SELECT count(*) FROM evidence_gaps "
                "WHERE control_id = :id AND gap_type = :gap_type AND status = 'open'"
            ),
            {"id": control_id, "gap_type": CONTROL_CHECK},
        ).scalar()
    finally:
        session.close()
    assert count == 1


def test_bad_ids_are_422(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Bad {uuid.uuid4().hex[:8]}")
    gap_id = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=control_id)
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    boolean_id = client.post(
        "/api/evidence-gaps",
        json={"gap_type": CONTROL_CHECK, "control_id": True},
    )
    boolean_evidence = client.post(
        f"/api/evidence-gaps/{gap_id}/resolve",
        json={"evidence_id": True},
    )
    blank = client.post("/api/evidence-gaps", json={"gap_type": "   "})
    too_long = client.post(
        "/api/evidence-gaps",
        json={"gap_type": "x" * 65, "control_id": control_id},
    )
    nul_type = client.post(
        "/api/evidence-gaps",
        json={"gap_type": "bad\x00type", "control_id": control_id},
    )
    nul_reason = client.post(
        "/api/evidence-gaps",
        json={"gap_type": CONTROL_CHECK, "control_id": control_id, "reason": "bad\x00reason"},
    )
    assert boolean_id.status_code == 422, boolean_id.text
    assert boolean_evidence.status_code == 422, boolean_evidence.text
    assert blank.status_code == 422, blank.text
    assert too_long.status_code == 422, too_long.text
    assert nul_type.status_code == 422, nul_type.text
    assert nul_reason.status_code == 422, nul_reason.text


def test_create_idempotency_key_is_bound_to_the_body(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Hash {uuid.uuid4().hex[:8]}")
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    body = {
        "gap_type": CONTROL_CHECK,
        "control_id": control_id,
        "reason": "first synthetic reason",
    }
    other = {**body, "reason": "second synthetic reason"}
    headers = {"Idempotency-Key": "body-hash"}
    before_gaps = _counts()["evidence_gaps"]
    before_keys = _counts()["idempotency_keys"]
    first = client.post("/api/evidence-gaps", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert "_request_sha256" not in first.json()
    mismatch = client.post("/api/evidence-gaps", json=other, headers=headers)
    assert mismatch.status_code == 422, mismatch.text
    assert _counts()["evidence_gaps"] == before_gaps + 1
    assert _counts()["idempotency_keys"] == before_keys + 1
    replay = client.post("/api/evidence-gaps", json=body, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    assert _counts()["evidence_gaps"] == before_gaps + 1


def test_legacy_create_key_replays_only_the_same_gap(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Legacy {uuid.uuid4().hex[:8]}")
    other_control = _control(actors["workspace_id"], f"Legacy other {uuid.uuid4().hex[:8]}")
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    body = {
        "gap_type": CONTROL_CHECK,
        "control_id": control_id,
        "reason": "legacy synthetic reason",
    }
    headers = {"Idempotency-Key": "legacy-key"}
    first = client.post("/api/evidence-gaps", json=body, headers=headers)
    assert first.status_code == 201, first.text
    session = _db()
    try:
        row = session.execute(
            text(
                "SELECT idempotency_key, response_body FROM idempotency_keys "
                "WHERE idempotency_key LIKE :needle"
            ),
            {"needle": "%:legacy-key"},
        ).one()
        stored = json.loads(row.response_body)
        stored.pop("_request_sha256", None)
        session.execute(
            text(
                "UPDATE idempotency_keys SET response_body = :body " "WHERE idempotency_key = :key"
            ),
            {"body": json.dumps(stored), "key": row.idempotency_key},
        )
        session.commit()
    finally:
        session.close()
    before = _counts()["evidence_gaps"]
    replay = client.post("/api/evidence-gaps", json=body, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert "_request_sha256" not in replay.json()
    assert _counts()["evidence_gaps"] == before
    mismatched = client.post(
        "/api/evidence-gaps",
        json={**body, "control_id": other_control, "reason": "other synthetic reason"},
        headers=headers,
    )
    assert mismatched.status_code == 409, mismatched.text
    assert _counts()["evidence_gaps"] == before


def test_idempotency_keys_do_not_collide_across_gaps(client):
    actors = _actors()
    first_control = _control(actors["workspace_id"], f"Key A {uuid.uuid4().hex[:8]}")
    second_control = _control(actors["workspace_id"], f"Key B {uuid.uuid4().hex[:8]}")
    first = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=first_control)
    second = _gap(actors["workspace_id"], gap_type=CONTROL_CHECK, control_id=second_control)
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    raw = "same-raw-key"
    accepted = client.post(
        f"/api/evidence-gaps/{first}/decision",
        json={"status": "accepted"},
        headers={"Idempotency-Key": raw},
    )
    dismissed = client.post(
        f"/api/evidence-gaps/{second}/decision",
        json={"status": "dismissed"},
        headers={"Idempotency-Key": raw},
    )
    assert accepted.status_code == 200, accepted.text
    assert dismissed.status_code == 200, dismissed.text
    assert accepted.json()["id"] == first
    assert accepted.json()["status"] == "accepted"
    assert dismissed.json()["id"] == second
    assert dismissed.json()["status"] == "dismissed"


def test_question_gap_resolves_only_when_the_answer_cites_the_document(client):
    actors = _actors()
    evidence_id, document_id = _evidence(actors["workspace_id"], approval="approved")
    session = _db()
    try:
        _sync_sequence(session, "questionnaires")
        qnr = Questionnaire(workspace_id=actors["workspace_id"], filename="q.txt", status="parsed")
        session.add(qnr)
        session.flush()
        _sync_sequence(session, "questions")
        question = Question(questionnaire_id=qnr.id, text="Synthetic question")
        session.add(question)
        session.flush()
        _sync_sequence(session, "chunks")
        chunk = Chunk(
            workspace_id=actors["workspace_id"],
            document_id=document_id,
            text="synthetic chunk",
        )
        session.add(chunk)
        session.flush()
        _sync_sequence(session, "answers")
        session.add(
            Answer(
                question_id=question.id,
                status="draft",
                citations=json.dumps([{"chunk_id": chunk.id, "snippet": "synthetic"}]),
            )
        )
        session.commit()
        question_id = question.id
    finally:
        session.close()
    gap_id = _gap(actors["workspace_id"], gap_type="missing_evidence", question_id=question_id)
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    resolved = client.post(
        f"/api/evidence-gaps/{gap_id}/resolve", json={"evidence_id": evidence_id}
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["close_reason"] == "answer_sufficient"
    assert resolved.json()["question_id"] == question_id
