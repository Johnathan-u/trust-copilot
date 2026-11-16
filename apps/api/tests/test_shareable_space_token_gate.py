"""Shareable-space tokens are admin-only, hashed at rest, and audited on use.

List and the detail serializer return access_token only as JSON null. A can_admin
caller also gets has_access_token. Everyone else does not. Create still returns the
raw token once. The stored credential is the SHA-256 hex digest, and a successful
public /access writes one audit row with the space id and nothing else about the token.
"""

import hashlib
import inspect
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from app.core.password import hash_password
from app.models.api_key import ApiKey
from app.models.audit_event import AuditEvent
from app.models.custom_role import CustomRole
from app.models.deal import Deal
from app.models.shareable_space import ShareableSpace
from app.models.user import User, WorkspaceMember
from app.models.user_session import UserSession
from app.services import shareable_space_service as ss

_PASSWORD = "spacepass"
_BUILTIN = {
    "builtin-admin": ("admin@trust.local", "a"),
    "builtin-editor": ("editor@trust.local", "e"),
    "builtin-reviewer": ("reviewer@trust.local", "r"),
}
# can_edit, can_review, can_export, can_admin
_CUSTOM = {
    "member": (False, False, False, False),
    "edit": (True, False, False, False),
    "export": (False, False, True, False),
    "review": (False, True, False, False),
    "adminflag": (False, False, False, True),
}
_ADMIN_ACTORS = {"builtin-admin", "adminflag"}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _login(client, email, password):
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client


def _see(db):
    db.rollback()
    db.expire_all()


def _audits(db, space_id):
    _see(db)
    return (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == "shareable_space.accessed",
            AuditEvent.resource_id == str(space_id),
        )
        .order_by(AuditEvent.id)
        .all()
    )


def _credentials(gate, actor):
    if actor in _BUILTIN:
        return _BUILTIN[actor]
    return gate["users"][actor], _PASSWORD


def _space_from(response, space_id):
    rows = [row for row in response.json()["spaces"] if row["id"] == space_id]
    assert len(rows) == 1
    return rows[0]


def _assert_hidden(response, item, raw, digest, *, indicator):
    assert item.get("access_token") is None
    if indicator:
        assert item.get("has_access_token") is True
    else:
        assert "has_access_token" not in item
    assert raw not in response.text
    assert digest not in response.text


@pytest.fixture
def gate(client, db_session):
    suffix = secrets.token_hex(4)
    users = {}
    roles = {}
    user_ids = []
    role_ids = []
    key_ids = []
    space_ids = []
    for name, (can_edit, can_review, can_export, can_admin) in _CUSTOM.items():
        role_name = f"sp{name[:6]}{suffix}"
        roles[name] = role_name
        role = CustomRole(
            workspace_id=1,
            name=role_name,
            can_edit=can_edit,
            can_review=can_review,
            can_export=can_export,
            can_admin=can_admin,
        )
        db_session.add(role)
        db_session.flush()
        role_ids.append(role.id)
        email = f"space-{name}-{suffix}@trust.local"
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            display_name=f"Space {name}",
            email_verified=True,
        )
        db_session.add(user)
        db_session.flush()
        user_ids.append(user.id)
        db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role=role_name))
        users[name] = email
    db_session.commit()

    _login(client, "admin@trust.local", "a")
    created = client.post(
        "/api/shareable-spaces",
        json={
            "name": f"Token gate {suffix}",
            "buyer_company": "Synthetic Buyer",
            "article_ids": [11],
            "answer_ids": [22],
            "document_ids": [33],
        },
    )
    assert created.status_code == 200, created.text
    created_body = created.json()
    raw = created_body["access_token"]
    assert isinstance(raw, str) and raw.strip()
    space_id = created_body["id"]
    space_ids.append(space_id)
    client.cookies.clear()
    state = {
        "client": client,
        "db": db_session,
        "suffix": suffix,
        "space_id": space_id,
        "space_ids": space_ids,
        "raw": raw,
        "digest": _digest(raw),
        "users": users,
        "roles": roles,
        "key_ids": key_ids,
    }
    try:
        yield state
    finally:
        client.cookies.clear()
        db_session.rollback()
        if space_ids:
            db_session.query(AuditEvent).filter(
                AuditEvent.resource_type == "shareable_space",
                AuditEvent.resource_id.in_([str(i) for i in space_ids]),
            ).delete(synchronize_session=False)
            db_session.query(ShareableSpace).filter(ShareableSpace.id.in_(space_ids)).delete(
                synchronize_session=False
            )
        if user_ids:
            db_session.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db_session.query(AuditEvent).filter(AuditEvent.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db_session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        if key_ids:
            db_session.query(ApiKey).filter(ApiKey.id.in_(key_ids)).delete(
                synchronize_session=False
            )
        if role_ids:
            db_session.query(CustomRole).filter(CustomRole.id.in_(role_ids)).delete(
                synchronize_session=False
            )
        db_session.commit()


@pytest.mark.parametrize(
    ("actor", "sees_indicator"),
    [
        ("member", False),
        ("edit", False),
        ("export", False),
        ("review", False),
        ("adminflag", True),
        ("builtin-admin", True),
        ("builtin-editor", False),
        ("builtin-reviewer", False),
    ],
)
def test_list_hides_the_raw_token_below_can_admin(gate, actor, sees_indicator):
    client = gate["client"]
    email, password = _credentials(gate, actor)
    _login(client, email, password)
    response = client.get("/api/shareable-spaces")
    assert response.status_code == 200, response.text
    item = _space_from(response, gate["space_id"])
    _assert_hidden(response, item, gate["raw"], gate["digest"], indicator=sees_indicator)
    assert actor in _ADMIN_ACTORS or not sees_indicator


def test_api_key_list_follows_can_admin(gate):
    client = gate["client"]
    db = gate["db"]
    client.cookies.clear()
    cases = (
        (gate["roles"]["member"], False),
        (gate["roles"]["review"], False),
        (gate["roles"]["adminflag"], True),
        ("editor", False),
        ("reviewer", False),
        ("admin", True),
    )
    for role, sees_indicator in cases:
        raw_key = secrets.token_urlsafe(32)
        row = ApiKey(
            workspace_id=1,
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            label=f"space-{role}",
            role=role,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        gate["key_ids"].append(row.id)
        response = client.get(
            "/api/shareable-spaces",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert response.status_code == 200, response.text
        item = _space_from(response, gate["space_id"])
        _assert_hidden(response, item, gate["raw"], gate["digest"], indicator=sees_indicator)


def test_unauthenticated_list_is_401(gate):
    client = gate["client"]
    client.cookies.clear()
    response = client.get("/api/shareable-spaces")
    assert response.status_code == 401
    assert gate["raw"] not in response.text


def test_create_remains_can_admin_and_returns_the_raw_token_once(gate):
    client = gate["client"]
    denied = ("builtin-editor", "builtin-reviewer", "member", "review")
    allowed = ("adminflag", "builtin-admin")
    for actor in denied:
        email, password = _credentials(gate, actor)
        _login(client, email, password)
        response = client.post(
            "/api/shareable-spaces", json={"name": f"deny-{actor}-{gate['suffix']}"}
        )
        assert response.status_code == 403, response.text
    for actor in allowed:
        email, password = _credentials(gate, actor)
        _login(client, email, password)
        response = client.post(
            "/api/shareable-spaces", json={"name": f"allow-{actor}-{gate['suffix']}"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body["access_token"], str) and body["access_token"].strip()
        gate["space_ids"].append(body["id"])
        listed = client.get("/api/shareable-spaces")
        assert listed.status_code == 200, listed.text
        item = _space_from(listed, body["id"])
        _assert_hidden(
            listed, item, body["access_token"], _digest(body["access_token"]), indicator=True
        )
    client.cookies.clear()


def test_stored_credential_is_the_sha256_digest(gate):
    db = gate["db"]
    _see(db)
    row = db.get(ShareableSpace, gate["space_id"])
    assert row is not None
    assert row.access_token != gate["raw"], "stored access_token is the raw secret"
    assert getattr(row, "token_hash", None) == gate["digest"]
    assert row.access_token is None
    assert row.is_active is True
    assert row.expires_at is not None


def test_plaintext_column_is_not_accepted(gate):
    db = gate["db"]
    client = gate["client"]
    raw = secrets.token_urlsafe(32)
    legacy = ShareableSpace(
        workspace_id=1,
        name=f"Legacy plaintext {gate['suffix']}",
        access_token=raw,
        is_active=True,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2),
    )
    db.add(legacy)
    db.commit()
    db.refresh(legacy)
    gate["space_ids"].append(legacy.id)
    client.cookies.clear()
    opened = client.get("/api/shareable-spaces/access", params={"token": raw})
    assert opened.status_code == 200, opened.text
    assert opened.json() == {"valid": False, "reason": "Space not found"}
    assert _audits(db, legacy.id) == []


def test_public_access_returns_ids_without_echoing_the_token(gate):
    client = gate["client"]
    client.cookies.clear()
    opened = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["valid"] is True
    assert body["article_ids"] == [11]
    assert body["answer_ids"] == [22]
    assert body["document_ids"] == [33]
    assert body["space"]["id"] == gate["space_id"]
    assert body["space"]["is_active"] is True
    assert body["space"]["access_token"] is None
    assert "has_access_token" not in body["space"]
    assert gate["raw"] not in opened.text
    assert gate["digest"] not in opened.text
    rejected = client.get("/api/shareable-spaces/access", params={"token": gate["digest"]})
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["valid"] is False


def test_successful_access_audits_space_id_only(gate):
    db = gate["db"]
    client = gate["client"]
    before = _audits(db, gate["space_id"])
    client.cookies.clear()
    first = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert first.status_code == 200 and first.json()["valid"] is True
    rows = _audits(db, gate["space_id"])
    assert len(rows) == len(before) + 1
    _assert_audit(rows[-1], gate)
    second = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert second.json()["valid"] is True
    again = _audits(db, gate["space_id"])
    assert len(again) == len(before) + 2
    _assert_audit(again[-1], gate)


def _assert_audit(row, gate):
    assert row.action == "shareable_space.accessed"
    assert row.resource_type == "shareable_space"
    assert row.resource_id == str(gate["space_id"])
    assert row.workspace_id == 1
    assert row.user_id is None
    assert row.email is None
    assert json.loads(row.details) == {"space_id": gate["space_id"]}
    blob = " ".join(
        str(part or "")
        for part in (row.action, row.email, row.resource_type, row.resource_id, row.details)
    )
    assert gate["raw"] not in blob
    assert gate["digest"] not in blob


def test_denied_access_does_not_audit(gate):
    db = gate["db"]
    client = gate["client"]
    client.cookies.clear()
    unknown = secrets.token_urlsafe(32)
    missing = client.get("/api/shareable-spaces/access", params={"token": unknown})
    assert missing.json() == {"valid": False, "reason": "Space not found"}
    _see(db)
    row = db.get(ShareableSpace, gate["space_id"])
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    db.commit()
    expired = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert expired.json() == {"valid": False, "reason": "Space expired"}
    assert _audits(db, gate["space_id"]) == []
    _login(client, "admin@trust.local", "a")
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    row.is_active = False
    db.commit()
    client.cookies.clear()
    inactive = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert inactive.json() == {"valid": False, "reason": "Space deactivated"}
    assert _audits(db, gate["space_id"]) == []


def test_deactivate_redacts_the_token_and_keeps_inactive(gate):
    client = gate["client"]
    _login(client, "admin@trust.local", "a")
    response = client.post(f"/api/shareable-spaces/{gate['space_id']}/deactivate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_active"] is False
    assert body["expires_at"]
    assert body.get("has_access_token") is True
    _assert_hidden(response, body, gate["raw"], gate["digest"], indicator=True)
    client.cookies.clear()
    opened = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert opened.json() == {"valid": False, "reason": "Space deactivated"}


def test_detail_serializer_redacts_the_token(gate):
    db = gate["db"]
    _see(db)
    detail = ss.get_space(db, gate["space_id"])
    assert detail is not None
    assert detail["access_token"] is None
    assert "has_access_token" not in detail
    encoded = json.dumps(detail)
    assert gate["raw"] not in encoded
    assert gate["digest"] not in encoded
    assert "include_admin_indicator" in inspect.signature(ss.get_space).parameters
    admin_view = ss.get_space(db, gate["space_id"], include_admin_indicator=True)
    assert admin_view["access_token"] is None
    assert admin_view["has_access_token"] is True
    admin_encoded = json.dumps(admin_view)
    assert gate["raw"] not in admin_encoded
    assert gate["digest"] not in admin_encoded


def test_hash_compare_is_constant_time():
    assert "compare_digest" in inspect.getsource(ss._same_hash)
    digest = hashlib.sha256(b"synthetic-space-token").hexdigest()
    assert ss._same_hash(digest, digest) is True
    assert ss._same_hash(None, digest) is False
    assert ss._same_hash("ab", digest) is False
    assert ss._same_hash("0" * 64, digest) is False


def test_no_detail_route_returns_the_token(gate):
    client = gate["client"]
    _login(client, "editor@trust.local", "e")
    response = client.get(f"/api/shareable-spaces/{gate['space_id']}")
    assert response.status_code in (404, 405)
    assert gate["raw"] not in response.text
    assert gate["digest"] not in response.text


def _rotation_audits(db, space_id):
    _see(db)
    return (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == "shareable_space.rotated",
            AuditEvent.resource_id == str(space_id),
        )
        .order_by(AuditEvent.id)
        .all()
    )


def _identity(row):
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "buyer_company": row.buyer_company,
        "buyer_email": row.buyer_email,
        "opportunity_id": row.opportunity_id,
        "description": row.description,
        "article_ids_json": row.article_ids_json,
        "answer_ids_json": row.answer_ids_json,
        "document_ids_json": row.document_ids_json,
        "is_active": row.is_active,
        "expires_at": row.expires_at,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at,
        "access_token": row.access_token,
    }


def _stamp_contents(db, space_id):
    _see(db)
    row = db.get(ShareableSpace, space_id)
    row.buyer_email = "buyer@example.com"
    row.opportunity_id = "opp-synthetic"
    row.description = "room notes"
    db.commit()
    return row


def _issue_key(gate, role):
    db = gate["db"]
    raw_key = secrets.token_urlsafe(32)
    record = ApiKey(
        workspace_id=1,
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        label=f"rotate-{role}-{gate['suffix']}",
        role=role,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    gate["key_ids"].append(record.id)
    return raw_key


def _rotate(client, space_id, **kwargs):
    return client.post(f"/api/shareable-spaces/{space_id}/rotate", **kwargs)


_DENIED_ACTORS = (
    "builtin-editor",
    "builtin-reviewer",
    "member",
    "edit",
    "export",
    "review",
)


def test_rotation_replaces_token_and_preserves_the_space(gate):
    """Old token dies, the new one works, and the deal room link stays put."""
    client = gate["client"]
    db = gate["db"]
    _stamp_contents(db, gate["space_id"])
    deal = Deal(
        workspace_id=1,
        company_name="Synthetic Buyer",
        room_id=gate["space_id"],
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    deal_id = deal.id
    try:
        _see(db)
        before = db.get(ShareableSpace, gate["space_id"])
        preserved = _identity(before)
        previous_hash = before.token_hash
        _login(client, "admin@trust.local", "a")
        response = _rotate(client, gate["space_id"])
        assert response.status_code == 200, response.text
        body = response.json()
        raw = body["access_token"]
        assert isinstance(raw, str) and raw.strip()
        assert raw != gate["raw"]
        assert set(body) == {
            "id",
            "workspace_id",
            "name",
            "buyer_company",
            "buyer_email",
            "opportunity_id",
            "access_token",
            "is_active",
            "expires_at",
            "created_at",
            "has_access_token",
        }
        assert body["id"] == gate["space_id"]
        assert body["has_access_token"] is True
        assert body["is_active"] is True
        assert body["buyer_email"] == "buyer@example.com"
        assert body["opportunity_id"] == "opp-synthetic"
        assert body["name"] == preserved["name"]
        assert body["expires_at"]
        _see(db)
        row = db.get(ShareableSpace, gate["space_id"])
        assert _identity(row) == preserved
        assert row.token_hash == _digest(raw)
        assert row.token_hash != previous_hash
        assert row.access_token is None
        linked = db.get(Deal, deal_id)
        assert linked.room_id == gate["space_id"]
        client.cookies.clear()
        old = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
        assert old.status_code == 200, old.text
        assert old.json() == {"valid": False, "reason": "Space not found"}
        opened = client.get("/api/shareable-spaces/access", params={"token": raw})
        assert opened.status_code == 200, opened.text
        assert opened.json()["valid"] is True
        assert opened.json()["space"]["id"] == gate["space_id"]
        assert opened.json()["article_ids"] == [11]
        assert opened.json()["answer_ids"] == [22]
        assert opened.json()["document_ids"] == [33]
        assert opened.json()["space"]["access_token"] is None
        assert raw not in opened.text
        _login(client, "admin@trust.local", "a")
        listed = client.get("/api/shareable-spaces")
        assert listed.status_code == 200, listed.text
        item = _space_from(listed, gate["space_id"])
        _assert_hidden(listed, item, raw, _digest(raw), indicator=True)
        assert gate["raw"] not in listed.text
        detail = ss.get_space(db, gate["space_id"], include_admin_indicator=True)
        encoded = json.dumps(detail)
        assert detail["access_token"] is None
        assert detail["has_access_token"] is True
        assert raw not in encoded
        assert _digest(raw) not in encoded
        missing = _rotate(client, 99999999)
        assert missing.status_code == 404
    finally:
        _see(db)
        db.query(Deal).filter(Deal.id == deal_id).delete(synchronize_session=False)
        db.commit()


@pytest.mark.parametrize("actor", _DENIED_ACTORS)
def test_non_admin_roles_cannot_rotate(gate, actor):
    client = gate["client"]
    db = gate["db"]
    email, password = _credentials(gate, actor)
    _login(client, email, password)
    _see(db)
    before = db.get(ShareableSpace, gate["space_id"])
    preserved = _identity(before)
    previous_hash = before.token_hash
    response = _rotate(client, gate["space_id"])
    assert response.status_code == 403, response.text
    assert gate["raw"] not in response.text
    assert gate["digest"] not in response.text
    _see(db)
    row = db.get(ShareableSpace, gate["space_id"])
    assert _identity(row) == preserved
    assert row.token_hash == previous_hash
    assert _rotation_audits(db, gate["space_id"]) == []


def test_api_key_rotate_follows_can_admin(gate):
    client = gate["client"]
    db = gate["db"]
    client.cookies.clear()
    denied = (
        (gate["roles"]["member"], False),
        (gate["roles"]["edit"], False),
        (gate["roles"]["export"], False),
        (gate["roles"]["review"], False),
        ("editor", False),
        ("reviewer", False),
    )
    _see(db)
    before = db.get(ShareableSpace, gate["space_id"])
    preserved = _identity(before)
    previous_hash = before.token_hash
    for role, _allowed in denied:
        raw_key = _issue_key(gate, role)
        response = _rotate(client, gate["space_id"], headers={"Authorization": f"Bearer {raw_key}"})
        assert response.status_code == 403, response.text
        assert gate["raw"] not in response.text
    _see(db)
    row = db.get(ShareableSpace, gate["space_id"])
    assert _identity(row) == preserved
    assert row.token_hash == previous_hash
    admin_key = _issue_key(gate, "admin")
    custom_key = _issue_key(gate, gate["roles"]["adminflag"])
    first = _rotate(client, gate["space_id"], headers={"Authorization": f"Bearer {admin_key}"})
    assert first.status_code == 200, first.text
    rotated = first.json()["access_token"]
    assert isinstance(rotated, str) and rotated != gate["raw"]
    listed = client.get(
        "/api/shareable-spaces",
        headers={"Authorization": f"Bearer {custom_key}"},
    )
    assert listed.status_code == 200, listed.text
    item = _space_from(listed, gate["space_id"])
    _assert_hidden(listed, item, rotated, _digest(rotated), indicator=True)
    second = _rotate(client, gate["space_id"], headers={"Authorization": f"Bearer {custom_key}"})
    assert second.status_code == 200, second.text
    again = second.json()["access_token"]
    assert again != rotated
    client.cookies.clear()
    dead = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert dead.json()["valid"] is False
    mid = client.get("/api/shareable-spaces/access", params={"token": rotated})
    assert mid.json()["valid"] is False
    live = client.get("/api/shareable-spaces/access", params={"token": again})
    assert live.json()["valid"] is True
    assert live.json()["space"]["id"] == gate["space_id"]


def test_other_workspace_rotate_is_404(gate):
    client = gate["client"]
    db = gate["db"]
    foreign_raw = secrets.token_urlsafe(32)
    foreign = ShareableSpace(
        workspace_id=2,
        name=f"Other workspace {gate['suffix']}",
        buyer_company="Other Buyer",
        buyer_email="other-buyer@example.com",
        access_token=None,
        token_hash=_digest(foreign_raw),
        is_active=True,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=4),
        article_ids_json=json.dumps([9]),
    )
    db.add(foreign)
    db.commit()
    db.refresh(foreign)
    gate["space_ids"].append(foreign.id)
    preserved = _identity(foreign)
    previous_hash = foreign.token_hash
    _login(client, "admin@trust.local", "a")
    own = _rotate(client, gate["space_id"])
    assert own.status_code == 200, own.text
    response = _rotate(client, foreign.id)
    assert response.status_code == 404, response.text
    assert foreign_raw not in response.text
    assert previous_hash not in response.text
    assert "Other Buyer" not in response.text
    _see(db)
    row = db.get(ShareableSpace, foreign.id)
    assert _identity(row) == preserved
    assert row.token_hash == previous_hash
    client.cookies.clear()
    opened = client.get("/api/shareable-spaces/access", params={"token": foreign_raw})
    assert opened.json()["valid"] is True


def test_inactive_and_expired_spaces_cannot_be_rotated(gate):
    client = gate["client"]
    db = gate["db"]
    _login(client, "admin@trust.local", "a")
    _see(db)
    row = db.get(ShareableSpace, gate["space_id"])
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    db.commit()
    _see(db)
    expired_before = _identity(db.get(ShareableSpace, gate["space_id"]))
    expired_hash = db.get(ShareableSpace, gate["space_id"]).token_hash
    expired = _rotate(client, gate["space_id"])
    assert expired.status_code == 409, expired.text
    assert expired.json()["detail"] == ss.ROTATION_EXPIRED
    assert gate["raw"] not in expired.text
    _see(db)
    after_expired = db.get(ShareableSpace, gate["space_id"])
    assert _identity(after_expired) == expired_before
    assert after_expired.token_hash == expired_hash
    assert after_expired.is_active is True
    assert _rotation_audits(db, gate["space_id"]) == []
    client.cookies.clear()
    still_expired = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert still_expired.json() == {"valid": False, "reason": "Space expired"}
    _login(client, "admin@trust.local", "a")
    _see(db)
    row = db.get(ShareableSpace, gate["space_id"])
    row.is_active = False
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    db.commit()
    _see(db)
    inactive_before = _identity(db.get(ShareableSpace, gate["space_id"]))
    inactive_hash = db.get(ShareableSpace, gate["space_id"]).token_hash
    inactive = _rotate(client, gate["space_id"])
    assert inactive.status_code == 409, inactive.text
    assert inactive.json()["detail"] == ss.ROTATION_INACTIVE
    _see(db)
    after_inactive = db.get(ShareableSpace, gate["space_id"])
    assert _identity(after_inactive) == inactive_before
    assert after_inactive.token_hash == inactive_hash
    assert after_inactive.is_active is False
    assert _rotation_audits(db, gate["space_id"]) == []
    client.cookies.clear()
    still_inactive = client.get("/api/shareable-spaces/access", params={"token": gate["raw"]})
    assert still_inactive.json() == {"valid": False, "reason": "Space deactivated"}


def test_rotation_audit_holds_space_id_only(gate, caplog):
    client = gate["client"]
    db = gate["db"]
    _stamp_contents(db, gate["space_id"])
    _login(client, "admin@trust.local", "a")
    with caplog.at_level("INFO", logger="app.services.shareable_space_service"):
        response = _rotate(client, gate["space_id"])
    assert response.status_code == 200, response.text
    raw = response.json()["access_token"]
    rows = _rotation_audits(db, gate["space_id"])
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "shareable_space.rotated"
    assert row.resource_type == "shareable_space"
    assert row.resource_id == str(gate["space_id"])
    assert row.workspace_id == 1
    assert row.user_id is None
    assert row.email is None
    assert json.loads(row.details) == {"space_id": gate["space_id"]}
    blob = " ".join(
        str(part or "")
        for part in (
            row.action,
            row.email,
            row.user_id,
            row.resource_type,
            row.resource_id,
            row.details,
        )
    )
    assert gate["raw"] not in blob
    assert raw not in blob
    assert gate["digest"] not in blob
    assert _digest(raw) not in blob
    assert "buyer@example.com" not in blob
    assert "Synthetic Buyer" not in blob
    assert "opp-synthetic" not in blob
    log_text = caplog.text
    assert "shareable_space.rotated" in log_text
    assert gate["raw"] not in log_text
    assert raw not in log_text
    assert gate["digest"] not in log_text
    assert _digest(raw) not in log_text
    assert "buyer@example.com" not in log_text


def test_custom_admin_can_rotate(gate):
    client = gate["client"]
    email, password = _credentials(gate, "adminflag")
    _login(client, email, password)
    response = _rotate(client, gate["space_id"])
    assert response.status_code == 200, response.text
    raw = response.json()["access_token"]
    assert isinstance(raw, str) and raw != gate["raw"]
    listed = client.get("/api/shareable-spaces")
    item = _space_from(listed, gate["space_id"])
    _assert_hidden(listed, item, raw, _digest(raw), indicator=True)


def test_unauthenticated_rotate_is_401(gate):
    client = gate["client"]
    client.cookies.clear()
    response = _rotate(client, gate["space_id"])
    assert response.status_code == 401
    assert gate["raw"] not in response.text
    _see(gate["db"])
    row = gate["db"].get(ShareableSpace, gate["space_id"])
    assert row.token_hash == gate["digest"]
