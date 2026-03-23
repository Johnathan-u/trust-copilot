"""TC-V-B2: Trust requests API verification. POST (public), GET list/id and PATCH status with require_can_review. TC-R-B4: suggest-reply. TC-H-B1: status workflow, audit, assignee. TC-H-B2: notes/replies, audit, email."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AuditEvent, TrustRequestNote


def test_create_trust_request_public(client: TestClient) -> None:
    """POST /api/trust-requests works without auth (public submit)."""
    r = client.post(
        "/api/trust-requests/",
        json={
            "requester_email": "customer@example.com",
            "requester_name": "Customer",
            "subject": "SOC 2",
            "message": "Please share your SOC 2 report.",
            "workspace_id": 1,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["requester_email"] == "customer@example.com"
    assert data["status"] == "new"
    assert data.get("id") is not None
    assert "created_at" in data


def test_list_trust_requests_requires_auth(client: TestClient) -> None:
    """GET /api/trust-requests without auth returns 401."""
    r = client.get("/api/trust-requests")
    assert r.status_code == 401


def test_list_trust_requests_with_session(client: TestClient) -> None:
    """GET /api/trust-requests with auth returns list; supports workspace_id, status."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/trust-requests")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)

    r2 = client.get("/api/trust-requests?workspace_id=1")
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)

    r3 = client.get("/api/trust-requests?status=new")
    assert r3.status_code == 200
    assert isinstance(r3.json(), list)


def test_get_trust_request_by_id(client: TestClient) -> None:
    """GET /api/trust-requests/{id} requires auth; returns request or 404/403."""
    # Create one as public
    create = client.post(
        "/api/trust-requests/",
        json={
            "requester_email": "get@example.com",
            "message": "Message",
            "workspace_id": 1,
        },
    )
    assert create.status_code == 200
    rid = create.json()["id"]

    r_anon = client.get(f"/api/trust-requests/{rid}")
    assert r_anon.status_code == 401

    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get(f"/api/trust-requests/{rid}")
    assert r.status_code == 200
    assert r.json()["id"] == rid
    assert r.json()["message"] == "Message"

    r404 = client.get("/api/trust-requests/999999")
    assert r404.status_code == 404


def test_patch_trust_request_status(client: TestClient) -> None:
    """PATCH /api/trust-requests/{id} updates status; requires can_review. TC-H-B1: canonical statuses."""
    create = client.post(
        "/api/trust-requests/",
        json={
            "requester_email": "patch@example.com",
            "message": "M",
            "workspace_id": 1,
        },
    )
    assert create.status_code == 200
    rid = create.json()["id"]

    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.patch(f"/api/trust-requests/{rid}", json={"status": "in_progress"})
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"

    r2 = client.patch(f"/api/trust-requests/{rid}", json={"status": "completed"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "completed"


def test_list_filter_by_status(client: TestClient) -> None:
    """List with status filter returns only matching requests. TC-H-B1: canonical status."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/trust-requests?status=completed")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert all(item["status"] == "completed" for item in items)


def test_suggest_reply_requires_auth(client: TestClient) -> None:
    """POST /api/trust-requests/{id}/suggest-reply requires auth (TC-R-B4)."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "suggest@example.com", "message": "Need info", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]

    r = client.post(f"/api/trust-requests/{rid}/suggest-reply")
    assert r.status_code == 401


def test_suggest_reply_returns_draft(client: TestClient) -> None:
    """POST /api/trust-requests/{id}/suggest-reply returns draft (mocked) (TC-R-B4)."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "draft@example.com", "message": "Please share compliance docs.", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]

    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    with patch("app.services.trust_request_draft.suggest_reply_draft", return_value="Thank you for your request. We will provide the information shortly."):
        r = client.post(f"/api/trust-requests/{rid}/suggest-reply")
    assert r.status_code == 200
    data = r.json()
    assert "draft" in data
    assert data["draft"] == "Thank you for your request. We will provide the information shortly."


def test_suggest_reply_503_when_no_draft(client: TestClient) -> None:
    """POST suggest-reply returns 503 when AI returns empty draft (e.g. no OPENAI_API_KEY)."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "empty@example.com", "message": "Need docs", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    with patch("app.services.trust_request_draft.suggest_reply_draft", return_value=""):
        r = client.post(f"/api/trust-requests/{rid}/suggest-reply")
    assert r.status_code == 503
    data = r.json()
    assert "detail" in data
    assert "OPENAI" in data["detail"] or "suggestion" in data["detail"].lower()


def test_suggest_reply_404_for_unknown(client: TestClient) -> None:
    """POST suggest-reply for non-existent request returns 404."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.post("/api/trust-requests/999999/suggest-reply")
    assert r.status_code == 404


def test_patch_invalid_status_rejected(client: TestClient) -> None:
    """PATCH with invalid status returns 400. TC-H-B1."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "invalid@example.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.patch(f"/api/trust-requests/{rid}", json={"status": "invalid_status"})
    assert r.status_code == 400
    assert "Invalid status" in (r.json().get("detail") or "")


def test_list_other_workspace_forbidden(client: TestClient) -> None:
    """List with workspace_id different from session workspace returns 403. TC-H-B1."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/trust-requests?workspace_id=999")
    assert r.status_code == 403
    assert "another workspace" in (r.json().get("detail") or "").lower()


def test_patch_assignee_not_in_workspace_rejected(client: TestClient, db_session: Session) -> None:
    """PATCH assignee_id to user not in request's workspace returns 400. TC-H-B1."""
    from app.core.password import hash_password
    from app.models import User, Workspace, WorkspaceMember

    # Ensure workspace 2 and a user only in workspace 2 exist
    ws2 = db_session.query(Workspace).filter(Workspace.id == 2).first()
    if not ws2:
        ws2 = Workspace(id=2, name="Other", slug="other")
        db_session.add(ws2)
        db_session.commit()
    other_user = db_session.query(User).filter(User.email == "other@trust.local").first()
    if not other_user:
        other_user = User(
            email="other@trust.local",
            password_hash=hash_password("x"),
            display_name="Other",
        )
        db_session.add(other_user)
        db_session.commit()
        db_session.refresh(other_user)
    mem2 = (
        db_session.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == 2, WorkspaceMember.user_id == other_user.id)
        .first()
    )
    if not mem2:
        db_session.add(WorkspaceMember(workspace_id=2, user_id=other_user.id, role="editor"))
        db_session.commit()

    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "a@b.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.patch(f"/api/trust-requests/{rid}", json={"assignee_id": other_user.id})
    assert r.status_code == 400
    assert "workspace" in (r.json().get("detail") or "").lower()


def test_trust_request_update_audit_persisted(client: TestClient, db_session: Session) -> None:
    """PATCH status change persists an audit event with old/new. TC-H-B1."""
    from app.models import AuditEvent, TrustRequest

    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "audit@example.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.patch(f"/api/trust-requests/{rid}", json={"status": "pending_review"})
    assert r.status_code == 200

    events = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == "trust_request.update", AuditEvent.resource_id == str(rid))
        .order_by(AuditEvent.id.desc())
        .limit(1)
        .all()
    )
    assert len(events) == 1
    import json
    details = events[0].details
    if isinstance(details, str):
        details = json.loads(details) if details else {}
    assert "old_status" in details and details["old_status"] == "new"
    assert "new_status" in details and details["new_status"] == "pending_review"


# --- TC-H-B2: Trust request notes and replies ---


def test_list_notes_requires_auth(client: TestClient) -> None:
    """GET /api/trust-requests/{id}/notes requires auth."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "n@x.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    r = client.get(f"/api/trust-requests/{rid}/notes")
    assert r.status_code == 401


def test_create_internal_note(client: TestClient) -> None:
    """POST /api/trust-requests/{id}/notes creates internal note; list returns it with author and type. TC-H-B2."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "note@example.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    r = client.post(f"/api/trust-requests/{rid}/notes", json={"body": "Internal note text"})
    assert r.status_code == 200
    data = r.json()
    assert data["body"] == "Internal note text"
    assert data.get("note_type") == "internal_note"
    assert data.get("author_id") is not None
    assert "created_at" in data

    list_r = client.get(f"/api/trust-requests/{rid}/notes")
    assert list_r.status_code == 200
    notes = list_r.json()
    assert len(notes) == 1
    assert notes[0]["body"] == "Internal note text"
    assert notes[0]["note_type"] == "internal_note"
    assert "author_email" in notes[0]
    assert "author_display_name" in notes[0]


def test_create_reply_without_email(client: TestClient) -> None:
    """POST /api/trust-requests/{id}/replies without send_email stores reply only. TC-H-B2."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "reply@example.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    r = client.post(f"/api/trust-requests/{rid}/replies", json={"body": "We will send the report soon.", "send_email": False})
    assert r.status_code == 200
    data = r.json()
    assert data["body"] == "We will send the report soon."
    assert data.get("note_type") == "reply"

    list_r = client.get(f"/api/trust-requests/{rid}/notes")
    assert list_r.status_code == 200
    notes = [n for n in list_r.json() if n.get("note_type") == "reply"]
    assert len(notes) == 1


def test_create_reply_with_email_mocked(client: TestClient) -> None:
    """POST /api/trust-requests/{id}/replies with send_email=True calls email service. TC-H-B2."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "emailreply@example.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    with patch("app.api.routes.trust_requests.send_trust_reply_email", return_value=True) as mock_send:
        r = client.post(
            f"/api/trust-requests/{rid}/replies",
            json={"body": "Reply with email.", "send_email": True},
        )
    assert r.status_code == 200
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs.get("to") == "emailreply@example.com"
    assert "Reply with email" in (kwargs.get("body") or "")


def test_reply_email_failure_does_not_break_db_write(client: TestClient, db_session: Session) -> None:
    """When send_email=True and email fails, reply is still stored and audit has email_sent false. TC-H-B2."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "fail@example.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    with patch("app.api.routes.trust_requests.send_trust_reply_email", side_effect=Exception("SMTP error")):
        r = client.post(
            f"/api/trust-requests/{rid}/replies",
            json={"body": "Reply despite email fail.", "send_email": True},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["body"] == "Reply despite email fail."

    note = db_session.query(TrustRequestNote).filter(TrustRequestNote.trust_request_id == rid, TrustRequestNote.body == "Reply despite email fail.").first()
    assert note is not None
    import json
    ev = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == "trust_request.reply_added", AuditEvent.resource_id == str(data["id"]))
        .order_by(AuditEvent.id.desc())
        .first()
    )
    assert ev is not None
    details = ev.details
    if isinstance(details, str):
        details = json.loads(details) if details else {}
    assert details.get("email_sent") is False


def test_notes_audit_persisted(client: TestClient, db_session: Session) -> None:
    """Creating internal note and reply each persist audit event with request_id, author_id, note_type. TC-H-B2."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "auditnote@example.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    client.post(f"/api/trust-requests/{rid}/notes", json={"body": "Audit note"})
    client.post(f"/api/trust-requests/{rid}/replies", json={"body": "Audit reply", "send_email": False})

    import json
    note_ev = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == "trust_request.note_added")
        .order_by(AuditEvent.id.desc())
        .first()
    )
    assert note_ev is not None
    d = note_ev.details
    if isinstance(d, str):
        d = json.loads(d) if d else {}
    assert d.get("trust_request_id") == rid and d.get("note_type") == "internal_note"

    reply_ev = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == "trust_request.reply_added")
        .order_by(AuditEvent.id.desc())
        .first()
    )
    assert reply_ev is not None
    d2 = reply_ev.details
    if isinstance(d2, str):
        d2 = json.loads(d2) if d2 else {}
    assert d2.get("trust_request_id") == rid and d2.get("note_type") == "reply"


def test_notes_cross_workspace_forbidden(client: TestClient, db_session: Session) -> None:
    """GET/POST notes for a request in another workspace returns 403. TC-H-B2."""
    from app.models import Workspace

    ws2 = db_session.query(Workspace).filter(Workspace.id == 2).first()
    if not ws2:
        ws2 = Workspace(id=2, name="Other", slug="other")
        db_session.add(ws2)
        db_session.commit()
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "other@example.com", "message": "M", "workspace_id": 2},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    r_get = client.get(f"/api/trust-requests/{rid}/notes")
    assert r_get.status_code == 403
    r_post = client.post(f"/api/trust-requests/{rid}/notes", json={"body": "Forbidden note"})
    assert r_post.status_code == 403
    r_reply = client.post(f"/api/trust-requests/{rid}/replies", json={"body": "Forbidden reply", "send_email": False})
    assert r_reply.status_code == 403


def test_notes_empty_body_rejected(client: TestClient) -> None:
    """POST notes/replies with empty body returns 400. TC-H-B2."""
    create = client.post(
        "/api/trust-requests/",
        json={"requester_email": "empty@example.com", "message": "M", "workspace_id": 1},
    )
    assert create.status_code == 200
    rid = create.json()["id"]
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})

    r1 = client.post(f"/api/trust-requests/{rid}/notes", json={"body": "   "})
    assert r1.status_code == 400
    r2 = client.post(f"/api/trust-requests/{rid}/replies", json={"body": "", "send_email": False})
    assert r2.status_code == 400


