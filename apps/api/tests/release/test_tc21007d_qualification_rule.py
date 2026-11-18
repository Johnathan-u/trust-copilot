"""TC-21-007d: coverage reuses the TC-21-003 qualification rule.

``compliance_coverage._evidence_is_current`` must call
``evidence_qualification.evidence_qualifies`` and keep coverage's own reason
codes. The two rules agree on every case below. A shared-rule rejection is not
reported as qualifies.
"""

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Document, EvidenceItem, EvidenceMetadata, Workspace
from app.services import compliance_coverage as coverage_mod
from app.services.evidence_qualification import evidence_qualifies

NOW = datetime(2026, 6, 1, 12, 0, 0)
TICKET = Path(__file__).resolve().parents[4] / "docs" / "release" / "tickets" / "TC-21-007.md"


def _sync_ids(db: Session) -> None:
    for table in ("workspaces", "documents", "evidence_items", "evidence_metadata"):
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
                "(SELECT COALESCE(MAX(id), 1) FROM " + table + "))"
            ),
            {"table": table},
        )


def _workspace(db: Session, name: str) -> Workspace:
    row = Workspace(name=name, slug=f"tc21007d-{name}-{uuid.uuid4().hex[:12]}")
    db.add(row)
    db.flush()
    return row


def _document(db: Session, workspace: Workspace, *, deleted: bool = False) -> Document:
    row = Document(
        workspace_id=workspace.id,
        storage_key=f"tc21007d/{uuid.uuid4().hex}",
        filename="synthetic.txt",
        status="uploaded",
        deleted_at=NOW if deleted else None,
    )
    db.add(row)
    db.flush()
    return row


def _evidence(
    db: Session,
    workspace: Workspace,
    *,
    approval: str = "approved",
    document: Document | None = None,
) -> EvidenceItem:
    row = EvidenceItem(
        workspace_id=workspace.id,
        document_id=None if document is None else document.id,
        source_type="manual" if document is None else "document",
        title="Synthetic evidence",
        approval_status=approval,
    )
    db.add(row)
    db.flush()
    return row


def _expires(db: Session, evidence: EvidenceItem, when: datetime | None) -> None:
    db.add(EvidenceMetadata(evidence_id=evidence.id, expires_at=when))
    db.flush()


def test_tc21007d_coverage_reuses_the_qualification_rule(migrated_db, db_session: Session):
    """Coverage and the evidence gate stay on one qualification rule."""
    del migrated_db
    _sync_ids(db_session)
    home = _workspace(db_session, "home")
    other = _workspace(db_session, "other")
    live = _document(db_session, home)
    removed = _document(db_session, home, deleted=True)
    foreign_doc = _document(db_session, other)

    manual = _evidence(db_session, home)
    undated = _evidence(db_session, home)
    _expires(db_session, undated, None)
    current = _evidence(db_session, home, document=live)
    _expires(db_session, current, NOW + timedelta(days=1))
    due = _evidence(db_session, home, document=live)
    _expires(db_session, due, NOW)
    expired = _evidence(db_session, home, document=live)
    _expires(db_session, expired, NOW - timedelta(days=1))
    mixed = _evidence(db_session, home, document=live)
    _expires(db_session, mixed, NOW + timedelta(days=2))
    _expires(db_session, mixed, NOW - timedelta(days=2))
    deleted = _evidence(db_session, home, document=removed)
    pending = _evidence(db_session, home, document=live, approval="pending")
    rejected = _evidence(db_session, home, approval="rejected")
    foreign_item = _evidence(db_session, other, document=foreign_doc)

    cases = (
        ("approved manual evidence", manual, "qualifies"),
        ("null expiry", undated, "qualifies"),
        ("future expiry", current, "qualifies"),
        ("expiry at the check time", due, "stale"),
        ("past expiry", expired, "stale"),
        ("one expired metadata row", mixed, "stale"),
        ("deleted document", deleted, "deleted_document"),
        ("pending approval", pending, "not_approved"),
        ("rejected evidence", rejected, "not_approved"),
        ("evidence in another workspace", foreign_item, "missing"),
    )
    for label, item, expected in cases:
        reason = coverage_mod._evidence_is_current(db_session, item, home.id, NOW)
        qualifies = evidence_qualifies(db_session, item, home.id, NOW)
        assert reason == expected, label
        assert (reason == "qualifies") is qualifies, label

    assert hasattr(coverage_mod, "evidence_qualifies"), (
        "compliance_coverage._evidence_is_current must call "
        "evidence_qualification.evidence_qualifies"
    )

    def _accept(*_args, **_kwargs) -> bool:
        _accept.calls += 1
        return True

    _accept.calls = 0
    with patch.object(coverage_mod, "evidence_qualifies", side_effect=_accept):
        assert (
            coverage_mod._evidence_is_current(db_session, pending, home.id, NOW) == "not_approved"
        )
        assert coverage_mod._evidence_is_current(db_session, expired, home.id, NOW) == "stale"
        assert (
            coverage_mod._evidence_is_current(db_session, deleted, home.id, NOW)
            == "deleted_document"
        )
        assert (
            coverage_mod._evidence_is_current(db_session, foreign_item, home.id, NOW) == "missing"
        )
        assert coverage_mod._evidence_is_current(db_session, manual, home.id, NOW) == "qualifies"
    assert _accept.calls == 5

    def _reject(*_args, **_kwargs) -> bool:
        _reject.calls += 1
        return False

    _reject.calls = 0
    with patch.object(coverage_mod, "evidence_qualifies", side_effect=_reject):
        blocked = coverage_mod._evidence_is_current(db_session, manual, home.id, NOW)
    assert _reject.calls == 1
    assert blocked == "missing"

    folded = " ".join(TICKET.read_text(encoding="utf-8").lower().split())
    assert "coverage stale means the evidence has expired" in folded
    assert "control engine's stale means the evidence qualifies" in folded
    assert "more than 180 days old" in folded
