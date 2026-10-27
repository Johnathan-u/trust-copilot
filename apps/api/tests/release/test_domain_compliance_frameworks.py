"""TC-21-001 framework catalog enablement on real PostgreSQL.

The list and enable routes keep their historical fields and refuse every
advertised framework while TC-01-007 is open. Synthetic dev keys are not a
production catalog. These tests use the application database, not a fake
pass: the suite skips only when PostgreSQL is unreachable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.services.framework_catalog_registry import (
    ADVERTISED_CATALOGS,
    CATALOG_CONTRACT_VERSION,
    ERROR_CONTRACT_VERSION,
    RIGHTS_TICKET,
)

API_ROOT = Path(__file__).resolve().parents[2]
LEAK = "ZZ-CONTROL-TEXT-SHOULD-NOT-LEAK-TC21001"
ADVERTISED_KEYS = [spec.catalog_key for spec in ADVERTISED_CATALOGS]


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _fresh():
    from app.core.database import SessionLocal

    return SessionLocal()


def _by_key(items: list[dict], catalog_key: str) -> dict:
    matches = [item for item in items if item.get("catalog_key") == catalog_key]
    assert len(matches) == 1, items
    return matches[0]


def _consumer_would_enable(item: dict) -> bool:
    """Mirror apps/web/lib/frameworkCatalog.ts isProductionCatalogEnabled."""
    dev = bool(
        item.get("dev_test_only")
        or item.get("synthetic_dev_content_present")
        or item.get("catalog_kind") == "dev_synthetic"
        or item.get("enablement_state") == "dev_only"
        or item.get("rights_status") == "dev_test_only"
        or item.get("licence_status") == "dev_test_only"
        or item.get("content_origin") == "dev_seed"
    )
    if dev:
        return False
    if item.get("production_catalog") is not True:
        return False
    if item.get("rights_status") != "cleared" or item.get("licence_status") != "cleared":
        return False
    if item.get("enablement_state") != "enabled":
        return False
    if not item.get("content_version"):
        return False
    return True


def test_list_reports_every_advertised_framework_blocked(client):
    _login(client, "reviewer@trust.local", "r")
    response = client.get("/api/compliance/frameworks")
    assert response.status_code == 200, response.text
    items = response.json()
    assert isinstance(items, list)
    for key in ADVERTISED_KEYS:
        item = _by_key(items, key)
        assert set(["id", "name", "version", "created_at"]).issubset(item)
        assert item["contract_version"] == CATALOG_CONTRACT_VERSION
        assert item["rights_status"] == "blocked_pending_rights"
        assert item["licence_status"] == "not_cleared"
        assert item["enablement_state"] == "blocked"
        assert item["catalog_kind"] == "advertised_blocked"
        assert item["production_catalog"] is False
        assert item["content_version"] is None
        assert item["rights_ticket"] == RIGHTS_TICKET
        assert item["dev_test_only"] is False
        assert item["controls_are_production_catalog"] is False
        assert item["source_provenance"]["content_included"] is False
        assert item["source_provenance"]["licensed_text_included"] is False
        assert item["blocked_reason"]
        assert _consumer_would_enable(item) is False
    assert all(item["production_catalog"] is False for item in items)
    assert all(_consumer_would_enable(item) is False for item in items)


def test_enable_refuses_rights_and_agrees_across_retry_and_new_session(client):
    _login(client, "admin@trust.local", "a")
    listed = client.get("/api/compliance/frameworks")
    assert listed.status_code == 200
    before = _by_key(listed.json(), "SOC2")

    first = client.post(
        "/api/compliance/frameworks/enable", json={"name": "SOC 2", "version": "2024"}
    )
    assert first.status_code == 409, first.text
    detail = first.json()["detail"]
    assert detail["contract_version"] == ERROR_CONTRACT_VERSION
    assert detail["code"] == "framework_rights_not_cleared"
    assert detail["retryable"] is False
    assert detail["partial_failure"] is False
    assert detail["catalog_key"] == "SOC2"
    assert detail["rights_status"] == "blocked_pending_rights"
    assert detail["enablement_state"] == "blocked"
    assert detail["rights_ticket"] == RIGHTS_TICKET
    assert detail["request_id"]
    assert "Pending content licensing" in detail["message"]
    assert "TC-01-007" not in detail["message"]
    assert LEAK not in json.dumps(detail)

    alias = client.post("/api/compliance/frameworks/enable", json={"name": "ISO/IEC 27001"})
    assert alias.status_code == 409
    assert alias.json()["detail"]["catalog_key"] == "ISO27001"
    assert alias.json()["detail"]["code"] == "framework_rights_not_cleared"

    again = client.post(
        "/api/compliance/frameworks/enable", json={"name": "SOC2", "version": "2024"}
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "framework_rights_not_cleared"

    refreshed = client.get("/api/compliance/frameworks")
    after = _by_key(refreshed.json(), "SOC2")
    assert after["id"] == before["id"]
    assert after["enablement_state"] == "blocked"
    assert after["production_catalog"] is False
    assert after["content_version"] is None
    assert after["version"] != "2024"

    session = _fresh()
    try:
        from app.models import Framework, FrameworkCatalogEvent

        rows = session.query(Framework).filter(Framework.catalog_key == "SOC2").all()
        assert len(rows) == 1
        assert rows[0].enablement_state == "blocked"
        assert rows[0].rights_status == "blocked_pending_rights"
        assert rows[0].production_catalog is False
        assert rows[0].licence_status == after["licence_status"]
        events = (
            session.query(FrameworkCatalogEvent)
            .filter(
                FrameworkCatalogEvent.catalog_key == "SOC2",
                FrameworkCatalogEvent.outcome == "refused_rights",
            )
            .all()
        )
        assert events
        assert all(event.workspace_id == 1 for event in events)
        assert all(event.actor_role == "admin" for event in events)
        assert all(event.detail and LEAK not in event.detail for event in events)
    finally:
        session.close()


# Owned by this test. The shared reviewer@trust.local membership is mutated by
# other modules (see TC-02-BUG-016) and must not be this test's precondition.
_PERM_WORKSPACE_SLUG = "tc02-bug016"
_PERM_REVIEWER_EMAIL = "tc02-bug016-reviewer@trust.local"
_PERM_REVIEWER_PASSWORD = "tc02-bug016-reviewer"
_PERM_EDITOR_EMAIL = "tc02-bug016-editor@trust.local"
_PERM_EDITOR_PASSWORD = "tc02-bug016-editor"


def _setup_permission_actors() -> dict[str, int]:
    """Create this test's workspace, reviewer, editor, and the HIPAA catalog row."""
    from app.core.password import hash_password
    from app.models import Framework, User, Workspace, WorkspaceMember

    session = _fresh()
    try:
        workspace = session.query(Workspace).filter(Workspace.slug == _PERM_WORKSPACE_SLUG).first()
        if workspace is None:
            # Migrations insert workspace id 1 explicitly, so a fresh database
            # leaves the serial sequence at 1 and the next insert collides.
            session.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), "
                    "(SELECT COALESCE(MAX(id), 1) FROM workspaces))"
                )
            )
            workspace = Workspace(name="TC-02-BUG-016", slug=_PERM_WORKSPACE_SLUG)
            session.add(workspace)
            session.flush()

        def ensure_member(email: str, password: str, display_name: str, role: str) -> User:
            user = session.query(User).filter(User.email == email).first()
            if user is None:
                user = User(
                    email=email,
                    password_hash=hash_password(password),
                    display_name=display_name,
                )
                session.add(user)
                session.flush()
            else:
                user.password_hash = hash_password(password)
            membership = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.workspace_id == workspace.id,
                )
                .first()
            )
            if membership is None:
                session.add(
                    WorkspaceMember(
                        workspace_id=workspace.id,
                        user_id=user.id,
                        role=role,
                        suspended=False,
                    )
                )
            else:
                membership.role = role
                membership.suspended = False
            return user

        reviewer = ensure_member(
            _PERM_REVIEWER_EMAIL, _PERM_REVIEWER_PASSWORD, "TC02 BUG016 Reviewer", "reviewer"
        )
        editor = ensure_member(
            _PERM_EDITOR_EMAIL, _PERM_EDITOR_PASSWORD, "TC02 BUG016 Editor", "editor"
        )
        hipaa_rows = session.query(Framework).filter(Framework.catalog_key == "HIPAA").all()
        if not hipaa_rows:
            session.add(
                Framework(
                    name="HIPAA",
                    version="rights-pending",
                    catalog_key="HIPAA",
                    rights_status="blocked_pending_rights",
                    licence_status="not_cleared",
                    enablement_state="blocked",
                    catalog_kind="advertised_blocked",
                    production_catalog=False,
                    scaffold_inserted=False,
                )
            )
        else:
            for row in hipaa_rows:
                row.enablement_state = "blocked"
                row.production_catalog = False
        session.commit()
        return {
            "workspace_id": workspace.id,
            "reviewer_id": reviewer.id,
            "editor_id": editor.id,
        }
    finally:
        session.close()


def test_permissions_deny_enable_and_anonymous_list(client):
    actors = _setup_permission_actors()
    client.cookies.clear()
    assert client.get("/api/compliance/frameworks").status_code == 401
    assert (
        client.post("/api/compliance/frameworks/enable", json={"name": "HIPAA"}).status_code == 401
    )

    session = _fresh()
    try:
        from app.models import FrameworkCatalogEvent, WorkspaceMember, User

        reviewer = session.query(User).filter(User.id == actors["reviewer_id"]).one()
        assert reviewer.email == _PERM_REVIEWER_EMAIL
        membership = (
            session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == reviewer.id,
                WorkspaceMember.workspace_id == actors["workspace_id"],
            )
            .one()
        )
        assert membership.role == "reviewer"
        assert membership.suspended is False
        editor_membership = (
            session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == actors["editor_id"],
                WorkspaceMember.workspace_id == actors["workspace_id"],
            )
            .one()
        )
        assert editor_membership.role == "editor"
        before_events = session.query(FrameworkCatalogEvent).count()
    finally:
        session.close()

    _login(client, _PERM_REVIEWER_EMAIL, _PERM_REVIEWER_PASSWORD)
    assert client.get("/api/compliance/frameworks").status_code == 200
    denied = client.post("/api/compliance/frameworks/enable", json={"name": "HIPAA"})
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Insufficient permissions"

    _login(client, _PERM_EDITOR_EMAIL, _PERM_EDITOR_PASSWORD)
    assert client.get("/api/compliance/frameworks").status_code == 200
    denied_editor = client.post("/api/compliance/frameworks/enable", json={"name": "CAIQ"})
    assert denied_editor.status_code == 403

    session = _fresh()
    try:
        from app.models import Framework, FrameworkCatalogEvent

        assert session.query(FrameworkCatalogEvent).count() == before_events
        row = session.query(Framework).filter(Framework.catalog_key == "HIPAA").one()
        assert row.enablement_state == "blocked"
        assert row.production_catalog is False
    finally:
        session.close()


def test_unknown_empty_and_dev_keys_are_refused_without_becoming_production(client):
    _login(client, "admin@trust.local", "a")
    empty = client.post("/api/compliance/frameworks/enable", json={"name": "   "})
    assert empty.status_code == 400
    assert empty.json()["detail"]["code"] == "framework_name_required"
    assert empty.json()["detail"]["contract_version"] == ERROR_CONTRACT_VERSION

    unknown = client.post(
        "/api/compliance/frameworks/enable", json={"name": "Not A Real Framework"}
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "framework_not_advertised"

    bare_nist = client.post("/api/compliance/frameworks/enable", json={"name": "NIST"})
    assert bare_nist.status_code == 400
    assert bare_nist.json()["detail"]["code"] == "framework_not_advertised"
    assert "NIST CSF 2" in bare_nist.json()["detail"]["message"]
    assert "NIST 800-53r5" in bare_nist.json()["detail"]["message"]
    assert "NIST 800-171r3" in bare_nist.json()["detail"]["message"]

    dev_key = client.post("/api/compliance/frameworks/enable", json={"name": "HITRUST-DEV-AC-01"})
    assert dev_key.status_code == 409
    assert dev_key.json()["detail"]["code"] == "framework_dev_catalog_not_production"
    assert dev_key.json()["detail"]["enablement_state"] == "dev_only"
    assert dev_key.json()["detail"]["retryable"] is False

    session = _fresh()
    try:
        from app.models import Framework

        soc = session.query(Framework).filter(Framework.catalog_key == "SOC2").one()
        version_before = soc.version
    finally:
        session.close()

    dev_version = client.post(
        "/api/compliance/frameworks/enable",
        json={"name": "SOC 2", "version": "CSF-dev"},
    )
    assert dev_version.status_code == 409
    assert dev_version.json()["detail"]["code"] == "framework_dev_catalog_not_production"

    rejected = client.post(
        "/api/compliance/frameworks/enable",
        json={"name": "SIG", "version": "1", "controls": ["not-a-catalog"]},
    )
    assert rejected.status_code == 422

    too_long = client.post(
        "/api/compliance/frameworks/enable",
        json={"name": "SIG", "version": "v" * 33},
    )
    assert too_long.status_code == 422

    session = _fresh()
    try:
        from app.models import Framework

        assert (
            session.query(Framework).filter(Framework.name == "Not A Real Framework").count() == 0
        )
        assert session.query(Framework).filter(Framework.name == "HITRUST-DEV-AC-01").count() == 0
        assert session.query(Framework).filter(Framework.name == "NIST").count() == 0
        soc = session.query(Framework).filter(Framework.catalog_key == "SOC2").one()
        assert soc.version == version_before
        assert soc.version != "CSF-dev"
        assert soc.enablement_state == "blocked"
        assert soc.production_catalog is False
        hitrust = session.query(Framework).filter(Framework.catalog_key == "HITRUST").one()
        assert hitrust.enablement_state == "blocked"
        assert hitrust.production_catalog is False
    finally:
        session.close()


def test_dev_seed_row_is_labelled_and_control_text_is_not_in_the_api(client):
    from app.models import Framework, FrameworkControl
    from app.services.framework_catalog import label_dev_framework_row

    session = _fresh()
    framework_id = None
    try:
        row = Framework(name="HITRUST", version="CSF-dev", scaffold_inserted=False)
        label_dev_framework_row(row)
        session.add(row)
        session.flush()
        framework_id = row.id
        session.add(
            FrameworkControl(
                framework_id=row.id,
                control_key="HITRUST-DEV-AC-01",
                title="placeholder",
                description=LEAK,
                category="dev",
                criticality="medium",
            )
        )
        session.commit()
    finally:
        session.close()

    try:
        _login(client, "reviewer@trust.local", "r")
        response = client.get("/api/compliance/frameworks")
        assert response.status_code == 200
        body = response.text
        assert LEAK not in body
        items = response.json()
        advertised = _by_key(items, "HITRUST")
        assert advertised["enablement_state"] == "blocked"
        assert advertised["production_catalog"] is False
        assert advertised["dev_test_only"] is False
        dev_rows = [
            item
            for item in items
            if item.get("catalog_key") is None and item.get("name") == "HITRUST"
        ]
        assert dev_rows
        assert all(item["dev_test_only"] is True for item in dev_rows)
        assert all(item["production_catalog"] is False for item in dev_rows)
        assert all(item["catalog_kind"] == "dev_synthetic" for item in dev_rows)
        assert all(_consumer_would_enable(item) is False for item in dev_rows)
        assert all(LEAK not in text_value for item in items for text_value in _strings(item))

        _login(client, "admin@trust.local", "a")
        enabled = client.post(
            "/api/compliance/frameworks/enable",
            json={"name": "HITRUST", "version": "CSF-dev"},
        )
        assert enabled.status_code == 409
        assert enabled.json()["detail"]["code"] == "framework_dev_catalog_not_production"
        assert LEAK not in enabled.text

        session = _fresh()
        try:
            advertised_row = (
                session.query(Framework).filter(Framework.catalog_key == "HITRUST").one()
            )
            assert advertised_row.enablement_state == "blocked"
            assert advertised_row.version != "CSF-dev"
            dev = session.query(Framework).filter(Framework.id == framework_id).one()
            assert dev.catalog_kind == "dev_synthetic"
            assert dev.enablement_state == "dev_only"
            assert dev.catalog_key is None
            assert dev.production_catalog is False
            from app.api.routes.compliance_mappings import _framework_id_by_name
            from app.services.framework_catalog import framework_ids_for_exact_name

            resolved = framework_ids_for_exact_name(session, "HITRUST")
            assert resolved == [advertised_row.id]
            assert framework_id not in resolved
            assert _framework_id_by_name(session, "HITRUST") == resolved
        finally:
            session.close()
    finally:
        session = _fresh()
        try:
            if framework_id is not None:
                session.query(FrameworkControl).filter(
                    FrameworkControl.framework_id == framework_id
                ).delete()
                session.query(Framework).filter(Framework.id == framework_id).delete()
                session.commit()
        finally:
            session.close()


def test_tampered_rights_are_rewritten_blocked_and_provenance_cannot_leak(client):
    session = _fresh()
    try:
        session.execute(
            text(
                """
                UPDATE frameworks
                SET rights_status = 'cleared',
                    licence_status = 'cleared',
                    enablement_state = 'blocked',
                    source_provenance = :leak
                WHERE catalog_key = 'CAIQ'
                """
            ),
            {"leak": LEAK},
        )
        session.commit()
    finally:
        session.close()

    _login(client, "reviewer@trust.local", "r")
    response = client.get("/api/compliance/frameworks")
    assert response.status_code == 200
    assert LEAK not in response.text
    item = _by_key(response.json(), "CAIQ")
    assert item["rights_status"] == "blocked_pending_rights"
    assert item["licence_status"] == "not_cleared"
    assert item["enablement_state"] == "blocked"
    assert item["production_catalog"] is False
    assert item["source_provenance"]["content_included"] is False

    session = _fresh()
    try:
        from app.models import Framework

        row = session.query(Framework).filter(Framework.catalog_key == "CAIQ").one()
        assert row.rights_status == "cleared"
        assert row.source_provenance == LEAK
        assert row.enablement_state == "blocked"
        assert row.production_catalog is False
        row.rights_status = "blocked_pending_rights"
        row.licence_status = "not_cleared"
        row.source_provenance = None
        session.commit()
    finally:
        session.close()


def test_get_does_not_write_and_enable_writes_only_the_audit_event(client):
    session = _fresh()
    try:
        before_rows = session.execute(
            text(
                """
                SELECT id, name, version, catalog_key, rights_status, licence_status,
                       enablement_state, catalog_kind, production_catalog, updated_at
                FROM frameworks ORDER BY id
                """
            )
        ).all()
        before_events = session.execute(
            text("SELECT count(*) FROM framework_catalog_events")
        ).scalar()
    finally:
        session.close()

    _login(client, "reviewer@trust.local", "r")
    listed = client.get("/api/compliance/frameworks")
    assert listed.status_code == 200
    assert all("TC-01-007" not in (item.get("blocked_reason") or "") for item in listed.json())

    session = _fresh()
    try:
        after_rows = session.execute(
            text(
                """
                SELECT id, name, version, catalog_key, rights_status, licence_status,
                       enablement_state, catalog_kind, production_catalog, updated_at
                FROM frameworks ORDER BY id
                """
            )
        ).all()
        assert after_rows == before_rows
        assert (
            session.execute(text("SELECT count(*) FROM framework_catalog_events")).scalar()
            == before_events
        )
        stored_name = session.execute(
            text("SELECT name FROM frameworks WHERE catalog_key = 'SOC2'")
        ).scalar()
    finally:
        session.close()

    _login(client, "admin@trust.local", "a")
    enabled = client.post("/api/compliance/frameworks/enable", json={"catalog_key": "SOC2"})
    assert enabled.status_code == 409
    assert enabled.json()["detail"]["code"] == "framework_rights_not_cleared"
    body = enabled.json()["detail"]
    assert body["catalog_key"] == "SOC2"
    assert "Pending content licensing" in body["message"]

    session = _fresh()
    try:
        after_enable = session.execute(
            text(
                """
                SELECT id, name, version, catalog_key, rights_status, licence_status,
                       enablement_state, catalog_kind, production_catalog, updated_at
                FROM frameworks ORDER BY id
                """
            )
        ).all()
        assert after_enable == before_rows
        event = (
            session.execute(
                text(
                    """
                    SELECT catalog_key, name, framework_id
                    FROM framework_catalog_events
                    WHERE catalog_key = 'SOC2'
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
            )
            .mappings()
            .one()
        )
        assert event["catalog_key"] == "SOC2"
        assert event["name"] == stored_name
        assert event["framework_id"] is not None
        assert (
            session.execute(text("SELECT count(*) FROM framework_catalog_events")).scalar()
            == before_events + 1
        )
    finally:
        session.close()


def test_partial_failure_foreign_key_keeps_catalog_blocked(client):
    _login(client, "admin@trust.local", "a")
    client.get("/api/compliance/frameworks")
    from app.models import User
    from app.services.framework_catalog import attempt_enable

    session = _fresh()
    try:
        admin = session.query(User).filter(User.email == "admin@trust.local").one()
        admin_id = admin.id
    finally:
        session.close()

    session = _fresh()
    try:
        result = attempt_enable(
            session,
            name="NIST 800-53r5",
            version=None,
            actor_user_id=admin_id,
            actor_role="admin",
            workspace_id=42424242,
            request_id="tc21001-partial",
        )
        assert result.http_status == 409
        assert result.partial_failure is True
        assert result.error["code"] == "framework_enablement_partial_failure"
        assert result.error["contract_version"] == ERROR_CONTRACT_VERSION
        assert result.error["retryable"] is True
        assert result.error["enablement_state"] == "blocked"
        assert result.error["rights_status"] == "blocked_pending_rights"
        assert result.error["catalog_key"] == "NIST_800_53_R5"
        assert {step["step"] for step in result.error["steps"]} == {
            "catalog_state",
            "audit_event",
            "production_enablement",
        }
        assert LEAK not in json.dumps(result.error)
    finally:
        session.close()

    session = _fresh()
    try:
        from app.models import Framework, FrameworkCatalogEvent

        row = session.query(Framework).filter(Framework.catalog_key == "NIST_800_53_R5").one()
        assert row.enablement_state == "blocked"
        assert row.production_catalog is False
        assert (
            session.query(FrameworkCatalogEvent)
            .filter(FrameworkCatalogEvent.request_id == "tc21001-partial")
            .count()
            == 0
        )
    finally:
        session.close()

    _login(client, "admin@trust.local", "a")
    retried = client.post("/api/compliance/frameworks/enable", json={"name": "NIST 800-53r5"})
    assert retried.status_code == 409
    assert retried.json()["detail"]["code"] == "framework_rights_not_cleared"
    assert retried.json()["detail"]["partial_failure"] is False

    session = _fresh()
    try:
        from app.models import Framework, FrameworkCatalogEvent

        row = session.query(Framework).filter(Framework.catalog_key == "NIST_800_53_R5").one()
        assert row.enablement_state == "blocked"
        assert row.production_catalog is False
        assert (
            session.query(FrameworkCatalogEvent)
            .filter(
                FrameworkCatalogEvent.catalog_key == "NIST_800_53_R5",
                FrameworkCatalogEvent.outcome == "refused_rights",
            )
            .count()
            >= 1
        )
    finally:
        session.close()


def test_foreign_keys_and_production_check_on_postgres(client, db_session):
    _login(client, "admin@trust.local", "a")
    client.get("/api/compliance/frameworks")
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO framework_controls (framework_id, control_key, criticality, created_at)
                VALUES (99999999, 'ZZ-MISSING', 'medium', now())
                """
            )
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO framework_catalog_events (
                    framework_id, workspace_id, outcome, error_code, contract_version, created_at
                ) VALUES (
                    99999999, 1, 'refused_rights', 'framework_rights_not_cleared',
                    'framework-catalog-error/v1', now()
                )
                """
            )
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO framework_catalog_events (
                    framework_id, workspace_id, actor_user_id, outcome, error_code, contract_version, created_at
                )
                SELECT id, 99999999, NULL, 'refused_rights', 'framework_rights_not_cleared',
                       'framework-catalog-error/v1', now()
                FROM frameworks WHERE catalog_key = 'SIG'
                """
            )
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE frameworks SET production_catalog = true WHERE catalog_key = 'SIG'")
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE frameworks SET enablement_state = 'enabled' WHERE catalog_key = 'SIG'")
        )
        db_session.commit()
    db_session.rollback()

    row = db_session.execute(
        text(
            "SELECT enablement_state, production_catalog FROM frameworks WHERE catalog_key = 'SIG'"
        )
    ).one()
    assert row.enablement_state == "blocked"
    assert row.production_catalog is False

    from sqlalchemy import inspect

    from app.models.framework import Framework

    bind = db_session.get_bind()
    insp = inspect(bind)
    index_names = {idx["name"] for idx in insp.get_indexes("frameworks")}
    assert "uq_frameworks_catalog_key" in index_names
    check_names = {item["name"] for item in insp.get_check_constraints("frameworks")}
    assert "ck_frameworks_production_blocked" in check_names
    assert any(
        idx.name == "uq_frameworks_catalog_key" and idx.unique
        for idx in Framework.__table__.indexes
    )
    assert any(
        constraint.name == "ck_frameworks_production_blocked"
        for constraint in Framework.__table__.constraints
    )
    for foreign_key in insp.get_foreign_keys("framework_catalog_events"):
        assert foreign_key["options"].get("ondelete") == "SET NULL"


def test_suspended_admin_is_denied_by_current_membership(client):
    from app.models import User, WorkspaceMember

    session = _fresh()
    membership_id = None
    try:
        admin = session.query(User).filter(User.email == "admin@trust.local").one()
        membership = (
            session.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == admin.id, WorkspaceMember.workspace_id == 1)
            .one()
        )
        membership_id = membership.id
        membership.suspended = True
        session.commit()
    finally:
        session.close()

    try:
        _login(client, "admin@trust.local", "a")
        assert client.get("/api/compliance/frameworks").status_code == 403
        denied = client.post("/api/compliance/frameworks/enable", json={"name": "SIG"})
        assert denied.status_code == 403
    finally:
        session = _fresh()
        try:
            membership = (
                session.query(WorkspaceMember).filter(WorkspaceMember.id == membership_id).one()
            )
            membership.suspended = False
            session.commit()
        finally:
            session.close()


MIGRATION_REVISION = "tc21001_framework_catalog_rights"


def _catalog_schema_present(conn) -> bool:
    rights = conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'frameworks' AND column_name = 'rights_status'
            """
        )
    ).scalar()
    events = conn.execute(text("SELECT to_regclass('public.framework_catalog_events')")).scalar()
    return rights is not None and events is not None


def test_migration_upgrade_downgrade_upgrade_again(client):
    """Upgrade, downgrade, and upgrade again on PostgreSQL, then the API stays blocked."""
    from app.core.database import engine

    env = os.environ.copy()
    env["TRUST_COPILOT_TESTING"] = "1"
    engine.dispose()

    def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=str(API_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def _version() -> str | None:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

    try:
        # The suite already upgraded to head. Step back, then exercise the revision twice.
        prepared = _alembic("downgrade", "075")
        assert prepared.returncode == 0, prepared.stderr + prepared.stdout
        with engine.connect() as conn:
            assert _catalog_schema_present(conn) is False
            conn.execute(
                text(
                    """
                    DELETE FROM framework_controls
                    WHERE framework_id IN (
                        SELECT id FROM frameworks
                        WHERE name IN ('SOC2', 'ZZ Legacy Untouched')
                    )
                    """
                )
            )
            conn.execute(
                text("DELETE FROM frameworks WHERE name IN ('SOC2', 'ZZ Legacy Untouched')")
            )
            conn.execute(
                text(
                    """
                    INSERT INTO frameworks (name, version, created_at) VALUES
                    ('SOC2', '', now()),
                    ('ZZ Legacy Untouched', 'v-keep', now())
                    """
                )
            )
            conn.commit()

        def _legacy_identity() -> list[tuple]:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT name, version, created_at
                        FROM frameworks
                        WHERE name IN ('SOC2', 'ZZ Legacy Untouched')
                        ORDER BY name
                        """
                    )
                ).all()
            return [(row.name, row.version, row.created_at) for row in rows]

        baseline = _legacy_identity()
        assert [(row[0], row[1]) for row in baseline] == [
            ("SOC2", ""),
            ("ZZ Legacy Untouched", "v-keep"),
        ]

        upgraded = _alembic("upgrade", MIGRATION_REVISION)
        assert upgraded.returncode == 0, upgraded.stderr + upgraded.stdout
        assert _version() == MIGRATION_REVISION
        with engine.connect() as conn:
            assert _catalog_schema_present(conn) is True
        assert _legacy_identity() == baseline

        downgraded = _alembic("downgrade", "075")
        assert downgraded.returncode == 0, downgraded.stderr + downgraded.stdout
        assert _version() == "075"
        with engine.connect() as conn:
            assert _catalog_schema_present(conn) is False
        assert _legacy_identity() == baseline

        again = _alembic("upgrade", MIGRATION_REVISION)
        assert again.returncode == 0, again.stderr + again.stdout
        assert _version() == MIGRATION_REVISION
        with engine.connect() as conn:
            assert _catalog_schema_present(conn) is True
            stored = conn.execute(
                text("SELECT name, version FROM frameworks WHERE name = 'SOC2'")
            ).one()
            assert stored.name == "SOC2"
            assert stored.version == ""
        assert _legacy_identity() == baseline
    finally:
        restored = _alembic("upgrade", "head")
        engine.dispose()
        assert restored.returncode == 0, restored.stderr + restored.stdout

    _login(client, "admin@trust.local", "a")
    response = client.get("/api/compliance/frameworks")
    assert response.status_code == 200, response.text
    items = response.json()
    for key in ADVERTISED_KEYS:
        item = _by_key(items, key)
        assert item["enablement_state"] == "blocked"
        assert item["rights_status"] == "blocked_pending_rights"
        assert item["production_catalog"] is False
        assert _consumer_would_enable(item) is False
        assert "TC-01-007" not in (item.get("blocked_reason") or "")
    soc = _by_key(items, "SOC2")
    assert soc["name"] == "SOC 2"
    assert soc["version"] == ""
