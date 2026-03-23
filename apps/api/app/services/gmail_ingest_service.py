"""Phase F: Gmail ingest — fetch emails from approved labels, create evidence items."""

import json
import logging

from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.models.evidence_item import EvidenceItem
from app.models.gmail_integration import GmailControlSuggestion, GmailIngestLabel, GmailIntegration
from app.services.gmail_service import decrypt_token, get_gmail_provider
from app.services.slack_ingest_service import suggest_controls_for_evidence

logger = logging.getLogger(__name__)

SUPPORTED_ATTACHMENT_TYPES = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt", ".md")


def _make_gmail_metadata(message_id: str, thread_id: str, sender: str, subject: str, date: str) -> str:
    return json.dumps({
        "gmail_message_id": message_id,
        "gmail_thread_id": thread_id,
        "sender": sender,
        "subject": subject,
        "date": date,
    })


def _evidence_exists(db: Session, workspace_id: int, message_id: str) -> bool:
    """Check dedup by gmail_message_id in source_metadata."""
    rows = db.query(EvidenceItem).filter(
        EvidenceItem.workspace_id == workspace_id,
        EvidenceItem.source_type == "gmail",
    ).all()
    for r in rows:
        if not r.source_metadata:
            continue
        try:
            meta = json.loads(r.source_metadata)
            if meta.get("gmail_message_id") == message_id:
                return True
        except (json.JSONDecodeError, TypeError):
            continue
    return False


def _attachment_exists(db: Session, workspace_id: int, message_id: str, filename: str) -> bool:
    rows = db.query(EvidenceItem).filter(
        EvidenceItem.workspace_id == workspace_id,
        EvidenceItem.source_type == "gmail",
    ).all()
    for r in rows:
        if not r.source_metadata:
            continue
        try:
            meta = json.loads(r.source_metadata)
            if meta.get("gmail_message_id") == message_id and meta.get("attachment_filename") == filename:
                return True
        except (json.JSONDecodeError, TypeError):
            continue
    return False


def ingest_email(
    db: Session,
    workspace_id: int,
    label_id: str,
    message_data: dict,
    admin_user_id: int | None = None,
    label_name: str | None = None,
) -> dict:
    """Ingest a single email + its attachments. Returns {"email_evidence_id": ..., "attachment_ids": [...]}."""
    msg_id = message_data.get("id", "")
    thread_id = message_data.get("threadId", "")
    subject = message_data.get("subject", "(no subject)")
    sender = message_data.get("from", "")
    date = message_data.get("date", "")
    snippet = message_data.get("snippet", "")

    result = {"email_evidence_id": None, "attachment_ids": []}

    # Ingest email body as evidence
    if not _evidence_exists(db, workspace_id, msg_id):
        title = subject[:500] or f"Gmail message {msg_id}"
        ev = EvidenceItem(
            workspace_id=workspace_id,
            source_type="gmail",
            title=title,
            source_metadata=_make_gmail_metadata(msg_id, thread_id, sender, subject, date),
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        result["email_evidence_id"] = ev.id

        persist_audit(
            db, "gmail.evidence_ingested",
            user_id=admin_user_id,
            workspace_id=workspace_id,
            resource_type="evidence_item",
            resource_id=ev.id,
            details={"message_id": msg_id, "subject": subject[:100], "sender": sender},
        )

    # Ingest attachments
    for att in message_data.get("attachments", []):
        filename = att.get("filename", "")
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        if ext not in SUPPORTED_ATTACHMENT_TYPES:
            continue
        if _attachment_exists(db, workspace_id, msg_id, filename):
            continue

        att_meta = json.dumps({
            "gmail_message_id": msg_id,
            "gmail_thread_id": thread_id,
            "attachment_filename": filename,
            "attachment_id": att.get("id", ""),
            "mime_type": att.get("mime_type", ""),
            "size": att.get("size", 0),
            "sender": sender,
            "subject": subject,
            "date": date,
        })
        att_ev = EvidenceItem(
            workspace_id=workspace_id,
            source_type="gmail",
            title=f"Attachment: {filename} (from: {subject[:100]})",
            source_metadata=att_meta,
        )
        db.add(att_ev)
        db.commit()
        db.refresh(att_ev)
        result["attachment_ids"].append(att_ev.id)

        persist_audit(
            db, "gmail.attachment_ingested",
            user_id=admin_user_id,
            workspace_id=workspace_id,
            resource_type="evidence_item",
            resource_id=att_ev.id,
            details={"message_id": msg_id, "filename": filename},
        )

    return result


def fetch_and_ingest_label(
    db: Session,
    workspace_id: int,
    label_id: str,
    admin_user_id: int | None = None,
    limit: int = 20,
) -> dict:
    """Fetch recent emails from an approved Gmail label and ingest as evidence."""
    lbl = db.query(GmailIngestLabel).filter(
        GmailIngestLabel.workspace_id == workspace_id,
        GmailIngestLabel.label_id == label_id,
        GmailIngestLabel.enabled == True,
    ).first()
    if not lbl:
        return {"ingested": 0, "attachments": 0, "skipped": 0, "errors": ["Label not approved"]}

    gi = db.query(GmailIntegration).filter(
        GmailIntegration.workspace_id == workspace_id,
        GmailIntegration.enabled == True,
    ).first()
    if not gi:
        return {"ingested": 0, "attachments": 0, "skipped": 0, "errors": ["Gmail not connected"]}

    try:
        token = decrypt_token(gi.access_token_encrypted)
    except Exception as e:
        return {"ingested": 0, "attachments": 0, "skipped": 0, "errors": [f"Token error: {str(e)[:100]}"]}

    provider = get_gmail_provider()
    messages = provider.list_messages(token, label_id, max_results=limit)
    ingested = 0
    attachments = 0
    skipped = 0
    errors = []

    for msg_ref in messages:
        msg_id = msg_ref.get("id", "")
        if not msg_id:
            skipped += 1
            continue
        try:
            msg_data = provider.get_message(token, msg_id)
            if "error" in msg_data:
                errors.append(f"{msg_id}: {msg_data['error']}")
                continue
            result = ingest_email(db, workspace_id, label_id, msg_data, admin_user_id=admin_user_id, label_name=lbl.label_name)
            if result["email_evidence_id"]:
                ingested += 1
            else:
                skipped += 1
            attachments += len(result["attachment_ids"])
        except Exception as e:
            errors.append(f"{msg_id}: {str(e)[:100]}")

    return {"ingested": ingested, "attachments": attachments, "skipped": skipped, "errors": errors}
