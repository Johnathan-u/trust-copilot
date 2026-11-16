"""Room marker on GET /api/deals/{id}/room is limited to can_review or can_admin.

A signed-in custom role with neither flag must get a null access_token. Built-in
admin, editor, and reviewer, and custom roles with can_review or can_admin, still
receive the unstored marker. No session is 401. The marker is not a credential.
"""

import hashlib
import secrets

import pytest
from app.core.password import hash_password
from app.models.api_key import ApiKey
from app.models.audit_event import AuditEvent
from app.models.buyer_portal import BuyerPortal
from app.models.custom_role import CustomRole
from app.models.deal import Deal
from app.models.nda_access_request import NdaAccessRequest
from app.models.shareable_space import ShareableSpace
from app.models.user import User, WorkspaceMember
from app.models.user_session import UserSession
from app.models.vendor_request import VendorRequest

_PASSWORD = "room-token-pass"
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


def _login(client, email, password):
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client


def _room(client, deal_id):
    return client.get(f"/api/deals/{deal_id}/room")


@pytest.fixture
def room_gate(client, db_session):
    suffix = secrets.token_hex(4)
    users = {}
    roles = {}
    user_ids = []
    role_ids = []
    key_ids = []
    for name, (can_edit, can_review, can_export, can_admin) in _CUSTOM.items():
        role_name = f"rt{name[:4]}{suffix}"
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
        email = f"room-{name}-{suffix}@trust.local"
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            display_name=f"Room {name}",
            email_verified=True,
        )
        db_session.add(user)
        db_session.flush()
        user_ids.append(user.id)
        db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role=role_name))
        users[name] = email
    db_session.commit()

    _login(client, "admin@trust.local", "a")
    created = client.post("/api/deals", json={"company_name": f"Room Token {suffix}"})
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert "access_token" not in created_body
    deal_id = created_body["id"]
    client.cookies.clear()
    try:
        yield {
            "client": client,
            "db": db_session,
            "deal_id": deal_id,
            "users": users,
            "key_ids": key_ids,
            "roles": roles,
        }
    finally:
        client.cookies.clear()
        db_session.rollback()
        db_session.query(Deal).filter(Deal.id == deal_id).delete(synchronize_session=False)
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


def _credentials(room_gate, actor):
    if actor in _BUILTIN:
        return _BUILTIN[actor]
    return room_gate["users"][actor], _PASSWORD


@pytest.mark.parametrize(
    ("actor", "sees_token"),
    [
        ("member", False),
        ("edit", False),
        ("export", False),
        ("review", True),
        ("adminflag", True),
        ("builtin-admin", True),
        ("builtin-editor", True),
        ("builtin-reviewer", True),
    ],
)
def test_room_token_follows_can_review_or_admin(room_gate, actor, sees_token):
    client = room_gate["client"]
    deal_id = room_gate["deal_id"]
    email, password = _credentials(room_gate, actor)
    _login(client, email, password)
    response = _room(client, deal_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deal_id"] == deal_id
    assert isinstance(body["questionnaires"], list)
    assert isinstance(body["trust_center_articles"], list)
    token = body.get("access_token")
    if sees_token:
        assert isinstance(token, str) and token.strip()
    else:
        assert token is None


def test_api_key_room_token_follows_the_same_permission(room_gate):
    client = room_gate["client"]
    db = room_gate["db"]
    deal_id = room_gate["deal_id"]
    client.cookies.clear()
    cases = (
        (room_gate["roles"]["member"], False),
        ("reviewer", True),
        ("admin", True),
    )
    for role, sees_token in cases:
        raw = secrets.token_urlsafe(32)
        row = ApiKey(
            workspace_id=1,
            key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            label=f"room-{role}",
            role=role,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        room_gate["key_ids"].append(row.id)
        response = client.get(
            f"/api/deals/{deal_id}/room",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert response.status_code == 200, response.text
        token = response.json().get("access_token")
        if sees_token:
            assert isinstance(token, str) and token.strip()
        else:
            assert token is None


def test_unauthenticated_room_is_401(room_gate):
    client = room_gate["client"]
    client.cookies.clear()
    response = _room(client, room_gate["deal_id"])
    assert response.status_code == 401


def test_deal_reads_other_than_room_omit_the_marker(room_gate):
    client = room_gate["client"]
    deal_id = room_gate["deal_id"]
    _login(client, room_gate["users"]["member"], _PASSWORD)
    listed = client.get("/api/deals")
    assert listed.status_code == 200, listed.text
    deals = listed.json()["deals"]
    assert all("access_token" not in row for row in deals)
    detail = client.get(f"/api/deals/{deal_id}")
    assert detail.status_code == 200, detail.text
    assert "access_token" not in detail.json()
    risk = client.get(f"/api/deals/{deal_id}/risk")
    assert risk.status_code == 200, risk.text
    assert "access_token" not in risk.json()


def test_room_marker_is_not_stored_or_accepted(room_gate):
    client = room_gate["client"]
    db = room_gate["db"]
    deal_id = room_gate["deal_id"]
    _login(client, "admin@trust.local", "a")
    first = _room(client, deal_id)
    second = _room(client, deal_id)
    assert first.status_code == 200 and second.status_code == 200
    token = first.json()["access_token"]
    again = second.json()["access_token"]
    assert isinstance(token, str) and token.strip()
    assert token != again
    client.cookies.clear()

    space = client.get("/api/shareable-spaces/access", params={"token": token})
    assert space.status_code == 200, space.text
    assert space.json()["valid"] is False
    nda = client.get("/api/nda-access/validate", params={"token": token})
    assert nda.status_code == 200, nda.text
    assert nda.json()["valid"] is False
    portal = client.get(f"/public/buyer-portal/{token}/manifest")
    assert portal.status_code == 404
    vendor = client.get("/api/vendor-response", params={"token": token})
    assert vendor.status_code == 404

    assert db.query(ShareableSpace).filter(ShareableSpace.access_token == token).count() == 0
    assert db.query(NdaAccessRequest).filter(NdaAccessRequest.access_token == token).count() == 0
    assert db.query(BuyerPortal).filter(BuyerPortal.portal_token == token).count() == 0
    assert db.query(VendorRequest).filter(VendorRequest.link_token == token).count() == 0
    assert db.query(ShareableSpace).filter(ShareableSpace.access_token == again).count() == 0
