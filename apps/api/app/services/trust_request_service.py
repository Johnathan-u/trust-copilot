"""Bounded trust intake and durable reviewed-reply state transitions."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import idempotency
from app.core.auth_deps import _resolve_permission
from app.models import AuditEvent, TrustRequest, TrustRequestNote, User, WorkspaceMember
from app.models.trust_request_note import NOTE_TYPE_REPLY
from app.services.email_service import (
    ConsoleEmailProvider,
    DisabledEmailProvider,
    EmailMessage,
    get_email_provider,
)


def validate_mailbox(value: str) -> str:
    """Accept ordinary ASCII mailboxes; reject controls and ambiguous header syntax."""
    value = value.strip(" ").lower()
    if len(value) > 255 or not value.isascii() or value.count("@") != 1:
        raise ValueError("Enter a valid email address")
    local, domain = value.split("@")
    atoms = local.split(".")
    labels = domain.split(".")
    if (
        not local
        or len(local) > 64
        or any(not re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+", atom) for atom in atoms)
        or len(labels) < 2
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in labels)
        or not re.fullmatch(r"[a-z]{2,63}", labels[-1])
    ):
        raise ValueError("Enter a valid email address")
    return value


def validate_text(value: str | None) -> str | None:
    if value is not None:
        if "\0" in value:
            raise ValueError("Text contains an unsupported character")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Text contains an unsupported character") from None
    return value


def require_current_reviewer(db: Session, actor: dict, *, human: bool = False) -> None:
    """Recheck mutable membership; a signed session's role may be stale."""
    uid, workspace_id = actor.get("user_id"), actor.get("workspace_id")
    if uid is None and not human:
        # API-key permissions are read from the database by require_can_review.
        return
    member = (
        db.query(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == uid,
            WorkspaceMember.suspended.is_(False),
        )
        .first()
        if uid is not None
        else None
    )
    if member is None or not _resolve_permission(member.role, "can_review", workspace_id, db):
        raise HTTPException(403, "An active workspace reviewer is required.")


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def begin_intake(db: Session, workspace_id: int, client_key: str | None, digest: str):
    try:
        key = idempotency.scoped_key(workspace_id, "trust-intake", "create", client_key)
    except idempotency.IdempotencyKeyError as exc:
        raise HTTPException(422, str(exc)) from None
    if not key:
        return key, None, None
    cached = idempotency.get(db, key)
    if cached:
        if cached[1].get("request_hash") != digest:
            raise HTTPException(409, "This retry key was already used for a different request.")
        return key, None, cached[1]["response"]
    owner = idempotency.claim(db, key)
    if not owner:
        raise HTTPException(409, "A matching request is still being processed. Retry shortly.")
    return key, owner, None


def finish_intake(db: Session, key: str, owner: str | None, digest: str, response: dict) -> None:
    if key:
        idempotency.set(
            db, key, 200, {"request_hash": digest, "response": response}, owner=owner, commit=False
        )
    db.commit()


def abort_intake(db: Session, key: str, owner: str | None) -> None:
    db.rollback()
    if key and owner:
        idempotency.release(db, key, owner=owner)


def add_audit(
    db: Session, action: str, req: TrustRequest, note: TrustRequestNote, actor: dict
) -> None:
    db.add(
        AuditEvent(
            action=action,
            user_id=actor.get("user_id"),
            email=actor.get("email"),
            workspace_id=req.workspace_id,
            resource_type="trust_request_note",
            resource_id=str(note.id),
            details=json.dumps(
                {
                    "trust_request_id": req.id,
                    "body_revision": note.body_revision,
                    "author_id": note.author_id,
                    "note_type": note.note_type,
                    "delivery_status": note.delivery_status,
                }
            ),
        )
    )


def reply_for_update(
    db: Session, workspace_id: int, request_id: int, note_id: int, *, include_archived: bool = False
):
    request_query = db.query(TrustRequest).filter(
        TrustRequest.id == request_id,
        TrustRequest.workspace_id == workspace_id,
    )
    if not include_archived:
        request_query = request_query.filter(TrustRequest.deleted_at.is_(None))
    req = request_query.first()
    if req is None:
        raise HTTPException(404, "Reply not found")
    note = (
        db.query(TrustRequestNote)
        .filter(
            TrustRequestNote.id == note_id,
            TrustRequestNote.trust_request_id == req.id,
            TrustRequestNote.note_type == NOTE_TYPE_REPLY,
        )
        .with_for_update()
        .first()
    )
    if note is None:
        raise HTTPException(404, "Reply not found")
    return req, note


def require_revision(note: TrustRequestNote, revision: int) -> None:
    if (note.body_revision or 0) != revision:
        raise HTTPException(409, "The reply changed. Reload it before continuing.")


def edit_reply(
    db: Session,
    workspace_id: int,
    request_id: int,
    note_id: int,
    revision: int,
    body: str,
    actor: dict,
) -> TrustRequestNote:
    req, note = reply_for_update(db, workspace_id, request_id, note_id)
    require_revision(note, revision)
    if note.delivery_status in ("sending", "accepted", "uncertain"):
        raise HTTPException(409, "Create a new reply to change a message with a delivery attempt.")
    note.body = body
    note.body_revision = revision + 1
    note.approved_by = note.approved_at = note.approved_revision = note.approved_body_hash = None
    note.delivery_status = "draft"
    note.delivery_error = None
    add_audit(db, "trust_request.reply_edited", req, note, actor)
    db.commit()
    return note


def approve_reply(
    db: Session, workspace_id: int, request_id: int, note_id: int, revision: int, actor: dict
) -> TrustRequestNote:
    req, note = reply_for_update(db, workspace_id, request_id, note_id)
    require_current_reviewer(db, actor, human=True)
    uid = actor["user_id"]
    require_revision(note, revision)
    if note.delivery_status in ("sending", "accepted", "uncertain"):
        raise HTTPException(409, "This reply already has a delivery attempt.")
    if note.approved_revision == revision and note.approved_by and note.approved_at:
        return note
    note.approved_by = uid
    note.approved_at = datetime.now(timezone.utc)
    note.approved_revision = revision
    note.approved_body_hash = hashlib.sha256(note.body.encode()).hexdigest()
    note.delivery_status = "approved"
    add_audit(db, "trust_request.reply_approved", req, note, actor)
    db.commit()
    return note


def send_reply(
    db: Session, workspace_id: int, request_id: int, note_id: int, revision: int, actor: dict
) -> TrustRequestNote:
    req, note = reply_for_update(db, workspace_id, request_id, note_id)
    require_revision(note, revision)
    if (
        not note.approved_by
        or not note.approved_at
        or note.approved_revision != revision
        or note.approved_body_hash != hashlib.sha256(note.body.encode()).hexdigest()
    ):
        raise HTTPException(409, "Approve the current reply before sending it.")
    if note.delivery_status in ("accepted", "uncertain", "sending"):
        # A persisted intent survives a crash. Never resend a possibly accepted message.
        return note
    provider = get_email_provider()
    if isinstance(provider, (ConsoleEmailProvider, DisabledEmailProvider)):
        note.delivery_status = "unavailable"
        note.delivery_error = "delivery_unavailable"
        add_audit(db, "trust_request.reply_delivery_unavailable", req, note, actor)
        db.commit()
        return note
    if (note.delivery_attempts or 0) >= 10:
        raise HTTPException(409, "The delivery attempt limit has been reached.")
    message = EmailMessage(
        to=req.requester_email, subject=req.subject or "Re: Your trust request", body_text=note.body
    )
    note.delivery_status = "sending"
    note.delivery_started_at = datetime.now(timezone.utc)
    note.delivery_attempts = (note.delivery_attempts or 0) + 1
    note.delivery_error = None
    add_audit(db, "trust_request.reply_sending", req, note, actor)
    db.commit()  # Intent is durable before the network boundary.
    try:
        accepted = provider.send(message) is True
    except Exception:
        accepted = False
    # False/exception is uncertain: SMTP may have accepted before losing the response.
    req, note = reply_for_update(db, workspace_id, request_id, note_id, include_archived=True)
    note.delivery_status = "accepted" if accepted else "uncertain"
    note.delivery_error = None if accepted else "delivery_outcome_unknown"
    if accepted:
        note.delivery_accepted_at = datetime.now(timezone.utc)
    add_audit(db, "trust_request.reply_delivery_recorded", req, note, actor)
    db.commit()
    return note
