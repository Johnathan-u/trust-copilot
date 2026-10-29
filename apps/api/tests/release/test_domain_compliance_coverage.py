"""TC-21-007 reproducible framework coverage denominators.

Runs on PostgreSQL. Labels are synthetic, not framework text.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import (
    ControlEvidenceLink,
    CustomRole,
    Document,
    EvidenceItem,
    EvidenceMetadata,
    Framework,
    FrameworkControl,
    User,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
from app.services import compliance_coverage as coverage_mod
from app.services.compliance_coverage import CONTROL_COVERAGE_SCHEMA

SLUG = "tc21007"
ADMIN_EMAIL = "tc21007-admin@trust.local"
EDITOR_EMAIL = "tc21007-editor@trust.local"
REVIEWER_EMAIL = "tc21007-reviewer@trust.local"
NO_REVIEW_EMAIL = "tc21007-noreview@trust.local"
OTHER_EMAIL = "tc21007-other@trust.local"
ADMIN_PASSWORD = "test-a"
EDITOR_PASSWORD = "test-e"
REVIEWER_PASSWORD = "test-r"
NO_REVIEW_PASSWORD = "test-n"
OTHER_PASSWORD = "test-o"
NO_REVIEW_ROLE = "tc21007-noreview"
_COUNTED = (
    "control_evidence_links",
    "evidence_metadata",
    "evidence_items",
    "documents",
    "workspace_controls",
    "framework_controls",
    "frameworks",
    "custom_roles",
    "in_app_notifications",
    "audit_events",
    "user_sessions",
    "workspace_members",
    "users",
    "workspaces",
)
PRESERVED = (
    "kpi",
    "framework_coverage",
    "blind_spots",
    "weak_areas",
    "evidence_strength",
    "recommended_evidence",
    "trends",
    "drill_down",
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
            workspace = Workspace(name="TC-21-007", slug=SLUG)
            session.add(workspace)
            session.flush()
        other = session.query(Workspace).filter(Workspace.slug == SLUG + "-other").one_or_none()
        if other is None:
            _sync_sequence(session, "workspaces")
            other = Workspace(name="TC-21-007 other", slug=SLUG + "-other")
            session.add(other)
            session.flush()
        role = (
            session.query(CustomRole)
            .filter(CustomRole.workspace_id == workspace.id, CustomRole.name == NO_REVIEW_ROLE)
            .one_or_none()
        )
        if role is None:
            _sync_sequence(session, "custom_roles")
            role = CustomRole(
                workspace_id=workspace.id,
                name=NO_REVIEW_ROLE,
                description="Synthetic role with no review permission",
                can_edit=False,
                can_review=False,
                can_export=False,
                can_admin=False,
            )
            session.add(role)

        def member(email: str, password: str, role_name: str, ws: Workspace) -> User:
            user = session.query(User).filter(User.email == email).one_or_none()
            if user is None:
                _sync_sequence(session, "users")
                user = User(email=email, password_hash=hash_password(password), display_name=email)
                session.add(user)
                session.flush()
            else:
                user.password_hash = hash_password(password)
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


def _control(
    workspace_id: int,
    name: str,
    *,
    lifecycle: str | None = None,
    framework_control_id: int | None = None,
) -> int:
    session = _db()
    try:
        _sync_sequence(session, "workspace_controls")
        row = WorkspaceControl(
            workspace_id=workspace_id,
            status="not_implemented",
            custom_name=name,
            lifecycle=lifecycle,
            framework_control_id=framework_control_id,
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
            storage_key=f"tc21007/{uuid.uuid4().hex}",
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
        return row.id
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


def _coverage(client, control_id: int | None = None):
    params = {} if control_id is None else {"control_id": control_id}
    return client.get("/api/compliance-coverage", params=params)


def test_denial_at_each_permission_level(client):
    _actors()
    client.cookies.clear()
    assert client.get("/api/compliance-coverage").status_code == 401
    for role, email, password, code in (
        ("noreview", NO_REVIEW_EMAIL, NO_REVIEW_PASSWORD, 403),
        ("reviewer", REVIEWER_EMAIL, REVIEWER_PASSWORD, 200),
        ("editor", EDITOR_EMAIL, EDITOR_PASSWORD, 200),
        ("admin", ADMIN_EMAIL, ADMIN_PASSWORD, 200),
    ):
        _login(client, email, password)
        before = _counts()
        response = client.get("/api/compliance-coverage")
        assert response.status_code == code, (role, response.text)
        assert _counts() == before
        if code == 403:
            assert response.json()["detail"] == "Insufficient permissions"


def test_missing_and_foreign_control_ids_share_the_404(client):
    actors = _actors()
    foreign = _control(actors["other_workspace_id"], f"Foreign {uuid.uuid4().hex[:8]}")
    own = _control(actors["workspace_id"], f"Own {uuid.uuid4().hex[:8]}")
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    before = _counts()
    missing = _coverage(client, 999999991)
    other = _coverage(client, foreign)
    assert missing.status_code == 404
    assert missing.json() == other.json()
    assert missing.json() == {"detail": "Control not found"}
    found = _coverage(client, own)
    assert found.status_code == 200, found.text
    assert _counts() == before
    unscoped = _coverage(client)
    assert unscoped.json()["control_coverage"] == found.json()["control_coverage"]


def test_numerator_explanations_and_retry(client):
    actors = _actors()
    qualified = _control(actors["workspace_id"], f"Qualified {uuid.uuid4().hex[:8]}")
    approved = _evidence(actors["workspace_id"], approval="approved")
    _link(qualified, approved)
    negative = _control(actors["workspace_id"], f"Negative {uuid.uuid4().hex[:8]}")
    pending = _evidence(actors["workspace_id"], approval="pending")
    _link(negative, pending)
    bare = _control(actors["workspace_id"], f"Bare {uuid.uuid4().hex[:8]}")
    stale = _control(actors["workspace_id"], f"Stale {uuid.uuid4().hex[:8]}")
    stale_evidence = _evidence(actors["workspace_id"], approval="approved")
    _link(stale, stale_evidence)
    disabled = _control(
        actors["workspace_id"], f"Disabled {uuid.uuid4().hex[:8]}", lifecycle="disabled"
    )
    session = _db()
    try:
        session.add(
            EvidenceMetadata(
                evidence_id=stale_evidence, expires_at=datetime.utcnow() - timedelta(days=1)
            )
        )
        _sync_sequence(session, "frameworks")
        blocked_name = f"TC21007-BLOCK-{uuid.uuid4().hex[:8]}"
        framework = Framework(
            name=blocked_name,
            catalog_key=f"tc21007-{uuid.uuid4().hex[:12]}",
            rights_status="blocked_pending_rights",
            enablement_state="blocked",
            production_catalog=False,
        )
        session.add(framework)
        session.flush()
        _sync_sequence(session, "framework_controls")
        template = FrameworkControl(
            framework_id=framework.id,
            control_key="SYN-1",
            title="Synthetic template",
            criticality="medium",
        )
        session.add(template)
        session.flush()
        blocked_control = WorkspaceControl(
            workspace_id=actors["workspace_id"],
            status="not_implemented",
            custom_name="Blocked synthetic",
            framework_control_id=template.id,
        )
        session.add(blocked_control)
        session.commit()
        blocked_id = blocked_control.id
        framework_id = framework.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    before = _counts()
    first = _coverage(client)
    assert first.status_code == 200, first.text
    assert _counts() == before
    second = _coverage(client)
    assert second.json() == first.json()
    body = first.json()
    for key in PRESERVED:
        assert key in body
    coverage = body["control_coverage"]
    assert coverage["schema_version"] == CONTROL_COVERAGE_SCHEMA
    assert blocked_name not in first.text
    by_id = {item["control_id"]: item for item in coverage["explanations"]}
    assert by_id[qualified]["state"] == "qualified"
    assert by_id[qualified]["effect"] == "counted"
    assert by_id[qualified]["denominator_changed"] is False
    assert by_id[negative]["state"] == "gap"
    assert by_id[negative]["rule"] == "not_approved"
    assert by_id[negative]["effect"] == "excluded_from_numerator"
    assert by_id[bare]["rule"] == "no_evidence"
    assert by_id[stale]["state"] == "stale"
    assert by_id[stale]["rule"] == "expired"
    assert by_id[disabled]["state"] == "disabled"
    assert by_id[disabled]["denominator_changed"] is True
    assert by_id[disabled]["effect"] == "excluded_from_denominator"
    assert by_id[blocked_id]["state"] == "blocked"
    assert by_id[blocked_id]["rule"] == "framework_blocked"
    assert by_id[blocked_id]["framework_id"] == framework_id
    assert by_id[blocked_id]["denominator_changed"] is True
    assert coverage["qualified_control_ids"] == [qualified]
    assert coverage["numerator"] == 1
    applicable = [
        item["control_id"]
        for item in coverage["explanations"]
        if item["effect"] != "excluded_from_denominator"
    ]
    assert coverage["denominator"] == len(applicable)
    assert qualified in applicable
    assert stale in applicable
    assert negative in applicable
    assert bare in applicable
    assert disabled not in applicable
    assert blocked_id not in applicable
    stand_in = WorkspaceControl(
        id=88021013,
        workspace_id=actors["workspace_id"],
        status="not_implemented",
        custom_name="Missing template",
        framework_control_id=88021014,
    )
    explain_session = _db()
    try:
        unknown = coverage_mod._explain_control_inner(
            explain_session, stand_in, actors["workspace_id"]
        )
    finally:
        explain_session.close()
    assert unknown["state"] == "unknown"
    assert unknown["rule"] == "missing_framework"
    assert unknown["effect"] == "excluded_from_denominator"
    assert unknown["denominator_changed"] is True
    restarted = SessionLocal()
    try:
        again = coverage_mod.control_coverage(restarted, actors["workspace_id"])
    finally:
        restarted.close()
    assert again == coverage


def test_partial_failure_keeps_the_other_control(client):
    actors = _actors()
    kept = _control(actors["workspace_id"], f"Kept {uuid.uuid4().hex[:8]}")
    approved = _evidence(actors["workspace_id"], approval="approved")
    _link(kept, approved)
    broken = _control(actors["workspace_id"], f"Broken {uuid.uuid4().hex[:8]}")
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

    real = coverage_mod._explain_control_inner

    def explode(db, wc, workspace_id):
        if wc.id == broken:
            raise RuntimeError("forced coverage failure")
        return real(db, wc, workspace_id)

    with patch("app.services.compliance_coverage._explain_control_inner", side_effect=explode):
        response = _coverage(client)
    assert response.status_code == 200, response.text
    coverage = response.json()["control_coverage"]
    by_id = {item["control_id"]: item for item in coverage["explanations"]}
    assert by_id[kept]["state"] == "qualified"
    assert by_id[broken]["state"] == "failed"
    assert by_id[broken]["rule"] == "check_error"
    assert by_id[broken]["effect"] == "excluded_from_numerator"
    assert coverage["numerator"] == 1
    assert coverage["denominator"] == 2
    assert coverage["qualified_control_ids"] == [kept]
