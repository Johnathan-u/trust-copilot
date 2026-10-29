"""Shared canonical control contract for the legacy and compliance routes.

The legacy ``controls`` row and the compliance ``workspace_controls`` row keep
their existing columns. This module writes one lifecycle, owner, and version
slot onto both, and both routes read it back through ``canonical_payload``.

``content_version`` stays null. TC-01-007 has not cleared framework content,
and this module does not invent control text or a licensed version.

GET helpers only read. They do not repair drifted rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Control,
    ControlContractEvent,
    ControlEvidence,
    ControlEvidenceLink,
    Document,
    EvidenceItem,
    ExportRecord,
    Framework,
    FrameworkControl,
    TrustArticle,
    WorkspaceControl,
    WorkspaceMember,
)

CONTRACT_VERSION = "control-contract/v1"
EVIDENCE_CONTRACT_VERSION = "control-evidence/v1"
ERROR_CONTRACT_VERSION = "control-contract-error/v1"

LEGACY_TO_LIFECYCLE = {
    "in_review": "in_progress",
    "implemented": "implemented",
    "na": "not_implemented",
}
LIFECYCLE_TO_LEGACY = {
    "not_implemented": "na",
    "in_progress": "in_review",
    "implemented": "implemented",
    # The legacy status column has no verified value. The lifecycle field does.
    "verified": "implemented",
}
WORKSPACE_TO_LIFECYCLE = {
    "not_implemented": "not_implemented",
    "in_progress": "in_progress",
    "implemented": "implemented",
    "verified": "verified",
}
LIFECYCLE_TO_WORKSPACE = {
    "not_implemented": "not_implemented",
    "in_progress": "in_progress",
    "implemented": "implemented",
    "verified": "verified",
}


@dataclass
class ContractResult:
    http_status: int
    body: dict
    partial_failure: bool = False
    error: dict | None = None
    created: bool = False
    ids: dict = field(default_factory=dict)


def _canonical_unique_violation(exc: IntegrityError) -> bool:
    """True when the partial unique index on (workspace, canonical key) rejected a second row."""
    orig = getattr(exc, "orig", None)
    if getattr(orig, "pgcode", None) != "23505":
        return False
    message = str(orig).lower()
    return "canonical" in message


def canonical_key(framework: str, control_key: str) -> str:
    """Identity shared by both routes. Not a framework catalog title."""
    left = " ".join((framework or "").split())
    right = " ".join((control_key or "").split())
    return f"{left}:{right}"[:160]


def agreed_lifecycle(legacy: Control | None, workspace: WorkspaceControl | None) -> str | None:
    """One lifecycle for a pair. The workspace row wins when both exist.

    A missing stored lifecycle is projected in memory from the route status.
    Nothing is written.
    """
    if workspace is not None:
        if workspace.lifecycle:
            return workspace.lifecycle
        if workspace.status in WORKSPACE_TO_LIFECYCLE:
            return WORKSPACE_TO_LIFECYCLE[workspace.status]
    if legacy is not None:
        if legacy.lifecycle:
            return legacy.lifecycle
        if legacy.status in LEGACY_TO_LIFECYCLE:
            return LEGACY_TO_LIFECYCLE[legacy.status]
    return None


def status_aligned(legacy: Control | None, workspace: WorkspaceControl | None) -> bool:
    if legacy is None or workspace is None:
        return True
    if legacy.lifecycle and workspace.lifecycle:
        return legacy.lifecycle == workspace.lifecycle
    return True


def agreed_owner(
    legacy: Control | None, workspace: WorkspaceControl | None
) -> tuple[int | None, str | None]:
    if workspace is not None and (workspace.owner_user_id is not None or workspace.owner_team):
        return workspace.owner_user_id, workspace.owner_team
    if legacy is not None:
        return legacy.owner_user_id, legacy.owner_team
    if workspace is not None:
        return workspace.owner_user_id, workspace.owner_team
    return None, None


def evidence_summary(
    db: Session, legacy: Control | None, workspace: WorkspaceControl | None
) -> dict:
    legacy_count = 0
    mirrored = True
    if legacy is not None:
        rows = db.query(ControlEvidence).filter(ControlEvidence.control_id == legacy.id).all()
        legacy_count = len(rows)
        mirrored = all(row.evidence_item_id is not None for row in rows)
    canonical_count = 0
    if workspace is not None:
        canonical_count = (
            db.query(ControlEvidenceLink)
            .filter(ControlEvidenceLink.control_id == workspace.id)
            .count()
        )
    if legacy_count == 0:
        mirrored = canonical_count == 0 or mirrored
    return {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "workspace_scoped": True,
        "exactly_one_target": True,
        "legacy_count": legacy_count,
        "canonical_count": canonical_count,
        "mirrored": bool(mirrored and legacy_count == canonical_count),
    }


def canonical_payload(
    db: Session, legacy: Control | None, workspace: WorkspaceControl | None
) -> dict:
    key = None
    if workspace is not None and workspace.canonical_key:
        key = workspace.canonical_key
    elif legacy is not None and legacy.canonical_key:
        key = legacy.canonical_key
    elif legacy is not None and legacy.framework and legacy.control_id:
        key = canonical_key(legacy.framework, legacy.control_id)
    owner_user_id, owner_team = agreed_owner(legacy, workspace)
    return {
        "contract_version": CONTRACT_VERSION,
        "id": key,
        "version": None,
        "content_version": None,
        "owner_user_id": owner_user_id,
        "owner_team": owner_team,
        "lifecycle": agreed_lifecycle(legacy, workspace),
        "status_aligned": status_aligned(legacy, workspace),
        "evidence": evidence_summary(db, legacy, workspace),
    }


def legacy_for_workspace(db: Session, workspace: WorkspaceControl) -> Control | None:
    return (
        db.query(Control)
        .filter(Control.workspace_control_id == workspace.id)
        .order_by(Control.id)
        .first()
    )


def workspace_for_legacy(db: Session, legacy: Control) -> WorkspaceControl | None:
    if legacy.workspace_control_id is None:
        return None
    return (
        db.query(WorkspaceControl)
        .filter(
            WorkspaceControl.id == legacy.workspace_control_id,
            WorkspaceControl.workspace_id == legacy.workspace_id,
        )
        .first()
    )


def _owner_error(db: Session, workspace_id: int, owner_user_id: int | None) -> dict | None:
    if owner_user_id is None:
        return None
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == owner_user_id,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.suspended.is_(False),
        )
        .first()
    )
    if member is None:
        return {
            "contract_version": ERROR_CONTRACT_VERSION,
            "code": "owner_not_in_workspace",
            "message": "Owner not found",
            "retryable": False,
            "partial_failure": False,
        }
    return None


def _apply_pair(
    legacy: Control,
    workspace: WorkspaceControl,
    *,
    key: str,
    lifecycle: str,
    owner_user_id: int | None,
    owner_team: str | None,
    legacy_status: str,
    name: str | None,
) -> None:
    legacy.canonical_key = key
    legacy.content_version = None
    legacy.lifecycle = lifecycle
    legacy.status = legacy_status
    legacy.owner_user_id = owner_user_id
    legacy.owner_team = owner_team
    legacy.workspace_control_id = workspace.id
    if name is not None:
        legacy.name = name or None
    workspace.canonical_key = key
    workspace.content_version = None
    workspace.lifecycle = lifecycle
    workspace.status = LIFECYCLE_TO_WORKSPACE[lifecycle]
    workspace.owner_user_id = owner_user_id
    workspace.owner_team = owner_team
    if name is not None:
        workspace.custom_name = name or None


def _record_event(
    db: Session,
    *,
    event_workspace_id: int,
    legacy_id: int | None,
    workspace_control_id: int | None,
    key: str,
    lifecycle: str,
    request_id: str | None,
    outcome: str,
) -> str | None:
    if request_id:
        existing = (
            db.query(ControlContractEvent)
            .filter(
                ControlContractEvent.request_id == request_id,
                ControlContractEvent.canonical_key == key,
                ControlContractEvent.outcome == outcome,
            )
            .first()
        )
        if existing is not None:
            return None
    db.add(
        ControlContractEvent(
            workspace_id=event_workspace_id,
            legacy_control_id=legacy_id,
            workspace_control_id=workspace_control_id,
            canonical_key=key,
            lifecycle=lifecycle,
            request_id=request_id,
            outcome=outcome,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "foreign_key"
    return None


def _find_legacy(db: Session, workspace_id: int, key: str, framework: str, control_key: str):
    row = (
        db.query(Control)
        .filter(Control.workspace_id == workspace_id, Control.canonical_key == key)
        .order_by(Control.id)
        .first()
    )
    if row is not None:
        return row
    return (
        db.query(Control)
        .filter(
            Control.workspace_id == workspace_id,
            Control.framework == framework,
            Control.control_id == control_key,
        )
        .order_by(Control.id)
        .first()
    )


def _find_workspace(db: Session, workspace_id: int, key: str, linked_id: int | None):
    if linked_id is not None:
        row = (
            db.query(WorkspaceControl)
            .filter(
                WorkspaceControl.id == linked_id,
                WorkspaceControl.workspace_id == workspace_id,
            )
            .first()
        )
        if row is not None:
            return row
    return (
        db.query(WorkspaceControl)
        .filter(
            WorkspaceControl.workspace_id == workspace_id,
            WorkspaceControl.canonical_key == key,
        )
        .order_by(WorkspaceControl.id)
        .first()
    )


def upsert_legacy_control(
    db: Session,
    *,
    workspace_id: int,
    framework: str,
    control_key: str,
    name: str | None,
    legacy_status: str,
    owner_user_id: int | None,
    owner_team: str | None,
    request_id: str | None = None,
    event_workspace_id: int | None = None,
    legacy_id: int | None = None,
    _attempt: int = 0,
) -> ContractResult:
    """Create or reuse the legacy row and its compliance pair. Same input, same row.

    A concurrent insert that loses the partial unique index retries once and
    updates the row that won. It does not insert a second canonical key.
    """
    framework = " ".join(framework.split())
    control_key = " ".join(control_key.split())
    if not framework or not control_key:
        return ContractResult(
            400,
            {},
            error={"detail": "framework and control_id are required"},
        )
    if legacy_status not in LEGACY_TO_LIFECYCLE:
        return ContractResult(400, {}, error={"detail": "invalid status"})
    owner_problem = _owner_error(db, workspace_id, owner_user_id)
    if owner_problem:
        return ContractResult(404, {}, error=owner_problem)
    key = canonical_key(framework, control_key)
    lifecycle = LEGACY_TO_LIFECYCLE[legacy_status]
    try:
        if legacy_id is not None:
            legacy = (
                db.query(Control)
                .filter(Control.id == legacy_id, Control.workspace_id == workspace_id)
                .first()
            )
            if legacy is None:
                return ContractResult(404, {}, error={"detail": "Control not found"})
            other = _find_legacy(db, workspace_id, key, framework, control_key)
            if other is not None and other.id != legacy.id:
                return ContractResult(
                    409,
                    {},
                    error={
                        "contract_version": ERROR_CONTRACT_VERSION,
                        "code": "control_identity_conflict",
                        "message": "Another control already uses this framework and control id",
                        "retryable": False,
                        "partial_failure": False,
                    },
                )
            created = False
        else:
            legacy = _find_legacy(db, workspace_id, key, framework, control_key)
            created = legacy is None
        if legacy is None:
            legacy = Control(
                workspace_id=workspace_id,
                framework=framework,
                control_id=control_key,
                name=name,
                status=legacy_status,
            )
            db.add(legacy)
            db.flush()
        else:
            legacy.framework = framework
            legacy.control_id = control_key
        workspace = _find_workspace(db, workspace_id, key, legacy.workspace_control_id)
        if workspace is None:
            workspace = WorkspaceControl(
                workspace_id=workspace_id,
                status=LIFECYCLE_TO_WORKSPACE[lifecycle],
                custom_name=name,
            )
            db.add(workspace)
            db.flush()
        _apply_pair(
            legacy,
            workspace,
            key=key,
            lifecycle=lifecycle,
            owner_user_id=owner_user_id,
            owner_team=owner_team.strip() if owner_team else None,
            legacy_status=legacy_status,
            name=name,
        )
        for other in (
            db.query(Control)
            .filter(
                Control.workspace_id == workspace_id,
                Control.canonical_key == key,
                Control.id != legacy.id,
            )
            .all()
        ):
            other.lifecycle = lifecycle
            other.status = legacy_status
            other.content_version = None
            other.owner_user_id = owner_user_id
            other.owner_team = legacy.owner_team
            other.workspace_control_id = workspace.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _attempt or not _canonical_unique_violation(exc):
            raise
        return upsert_legacy_control(
            db,
            workspace_id=workspace_id,
            framework=framework,
            control_key=control_key,
            name=name,
            legacy_status=legacy_status,
            owner_user_id=owner_user_id,
            owner_team=owner_team,
            request_id=request_id,
            event_workspace_id=event_workspace_id,
            legacy_id=legacy_id,
            _attempt=1,
        )
    db.refresh(legacy)
    legacy_id = legacy.id
    workspace_id_row = workspace.id
    failure = _record_event(
        db,
        event_workspace_id=workspace_id if event_workspace_id is None else event_workspace_id,
        legacy_id=legacy_id,
        workspace_control_id=workspace_id_row,
        key=key,
        lifecycle=lifecycle,
        request_id=request_id,
        outcome="paired",
    )
    if failure:
        return ContractResult(
            409,
            {},
            partial_failure=True,
            error={
                "contract_version": ERROR_CONTRACT_VERSION,
                "code": "control_contract_partial_failure",
                "message": (
                    "The control was saved. The contract event could not be written "
                    "because a foreign-key check failed."
                ),
                "retryable": True,
                "partial_failure": True,
                "canonical_id": key,
                "lifecycle": lifecycle,
                "control_id": legacy_id,
                "steps": [
                    {"step": "control_pair", "status": "persisted"},
                    {"step": "contract_event", "status": "failed", "reason": failure},
                ],
            },
            created=created,
            ids={"legacy_id": legacy_id, "workspace_control_id": workspace_id_row},
        )
    legacy = db.query(Control).filter(Control.id == legacy_id).one()
    workspace = db.query(WorkspaceControl).filter(WorkspaceControl.id == workspace_id_row).one()
    return ContractResult(
        200,
        {},
        created=created,
        ids={"legacy_id": legacy_id, "workspace_control_id": workspace.id, "legacy": legacy},
    )


def upsert_workspace_control(
    db: Session,
    *,
    workspace_id: int,
    framework_control_id: int | None,
    custom_name: str | None,
    workspace_status: str,
    owner_user_id: int | None,
    owner_team: str | None,
    request_id: str | None = None,
    event_workspace_id: int | None = None,
) -> ContractResult:
    """Create or reuse a compliance control and the legacy row that shares its lifecycle."""
    if workspace_status not in WORKSPACE_TO_LIFECYCLE:
        return ContractResult(400, {}, error={"detail": "invalid status"})
    owner_problem = _owner_error(db, workspace_id, owner_user_id)
    if owner_problem:
        return ContractResult(404, {}, error=owner_problem)
    framework_name = "custom"
    control_key = " ".join((custom_name or "").split())
    if framework_control_id is not None:
        fc = db.query(FrameworkControl).filter(FrameworkControl.id == framework_control_id).first()
        if fc is None:
            return ContractResult(
                404,
                {},
                error={
                    "contract_version": ERROR_CONTRACT_VERSION,
                    "code": "framework_control_not_found",
                    "message": "Framework control not found",
                    "retryable": False,
                    "partial_failure": False,
                },
            )
        fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
        framework_name = fw.name if fw is not None and fw.name else "custom"
        control_key = fc.control_key
    if not control_key:
        return ContractResult(
            400,
            {},
            error={"detail": "custom_name or framework_control_id is required"},
        )
    lifecycle = WORKSPACE_TO_LIFECYCLE[workspace_status]
    legacy_status = LIFECYCLE_TO_LEGACY[lifecycle]
    display = " ".join((custom_name or "").split()) or None
    result = upsert_legacy_control(
        db,
        workspace_id=workspace_id,
        framework=framework_name,
        control_key=control_key,
        name=display,
        legacy_status=legacy_status,
        owner_user_id=owner_user_id,
        owner_team=owner_team,
        request_id=request_id,
        event_workspace_id=event_workspace_id,
    )
    if result.partial_failure or result.error:
        return result
    legacy = result.ids["legacy"]
    workspace = workspace_for_legacy(db, legacy)
    if workspace is not None and framework_control_id is not None:
        workspace.framework_control_id = framework_control_id
        db.commit()
    result.ids["workspace"] = workspace
    return result


def sync_workspace_row(
    db: Session,
    workspace: WorkspaceControl,
    *,
    request_id: str | None = None,
    event_workspace_id: int | None = None,
    _attempt: int = 0,
) -> ContractResult:
    """Copy this compliance row's lifecycle onto the legacy row. Does not insert a second pair."""
    if workspace.status not in WORKSPACE_TO_LIFECYCLE:
        return ContractResult(400, {}, error={"detail": "invalid status"})
    owner_problem = _owner_error(db, workspace.workspace_id, workspace.owner_user_id)
    if owner_problem:
        return ContractResult(404, {}, error=owner_problem)
    framework_name = "custom"
    control_key = " ".join((workspace.custom_name or "").split())
    if workspace.framework_control_id is not None:
        fc = (
            db.query(FrameworkControl)
            .filter(FrameworkControl.id == workspace.framework_control_id)
            .first()
        )
        if fc is not None:
            fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
            framework_name = fw.name if fw is not None and fw.name else framework_name
            control_key = fc.control_key
    if not control_key and workspace.canonical_key and ":" in workspace.canonical_key:
        framework_name, control_key = workspace.canonical_key.split(":", 1)
    if not control_key:
        control_key = f"control-{workspace.id}"
    key = canonical_key(framework_name, control_key)
    lifecycle = WORKSPACE_TO_LIFECYCLE[workspace.status]
    try:
        legacy = legacy_for_workspace(db, workspace)
        if legacy is None:
            legacy = _find_legacy(db, workspace.workspace_id, key, framework_name, control_key)
        created = legacy is None
        if legacy is None:
            legacy = Control(
                workspace_id=workspace.workspace_id,
                framework=framework_name,
                control_id=control_key,
                name=workspace.custom_name,
                status=LIFECYCLE_TO_LEGACY[lifecycle],
            )
            db.add(legacy)
            db.flush()
        else:
            legacy.framework = framework_name
            legacy.control_id = control_key
        _apply_pair(
            legacy,
            workspace,
            key=key,
            lifecycle=lifecycle,
            owner_user_id=workspace.owner_user_id,
            owner_team=workspace.owner_team,
            legacy_status=LIFECYCLE_TO_LEGACY[lifecycle],
            name=workspace.custom_name,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _attempt or not _canonical_unique_violation(exc):
            raise
        db.refresh(workspace)
        return sync_workspace_row(
            db,
            workspace,
            request_id=request_id,
            event_workspace_id=event_workspace_id,
            _attempt=1,
        )
    db.refresh(legacy)
    failure = _record_event(
        db,
        event_workspace_id=(
            workspace.workspace_id if event_workspace_id is None else event_workspace_id
        ),
        legacy_id=legacy.id,
        workspace_control_id=workspace.id,
        key=key,
        lifecycle=lifecycle,
        request_id=request_id,
        outcome="paired",
    )
    if failure:
        return ContractResult(
            409,
            {},
            partial_failure=True,
            error={
                "contract_version": ERROR_CONTRACT_VERSION,
                "code": "control_contract_partial_failure",
                "message": (
                    "The control was saved. The contract event could not be written "
                    "because a foreign-key check failed."
                ),
                "retryable": True,
                "partial_failure": True,
                "canonical_id": key,
                "lifecycle": lifecycle,
                "control_id": legacy.id,
                "steps": [
                    {"step": "control_pair", "status": "persisted"},
                    {"step": "contract_event", "status": "failed", "reason": failure},
                ],
            },
            created=created,
        )
    return ContractResult(200, {}, created=created, ids={"legacy": legacy, "workspace": workspace})


def delete_legacy_control(db: Session, legacy: Control) -> None:
    """Remove the legacy row. Drop the paired compliance row only when it has no evidence."""
    workspace = workspace_for_legacy(db, legacy)
    legacy.workspace_control_id = None
    db.flush()
    if workspace is not None:
        others = (
            db.query(Control)
            .filter(Control.workspace_control_id == workspace.id, Control.id != legacy.id)
            .count()
        )
        links = (
            db.query(ControlEvidenceLink)
            .filter(ControlEvidenceLink.control_id == workspace.id)
            .count()
        )
        if others == 0 and links == 0:
            db.delete(workspace)
    db.delete(legacy)
    db.commit()


def _existing_evidence(
    db: Session,
    control_id: int,
    *,
    document_id: int | None,
    trust_article_id: int | None,
    export_record_id: int | None,
) -> ControlEvidence | None:
    q = db.query(ControlEvidence).filter(ControlEvidence.control_id == control_id)
    if document_id is not None:
        q = q.filter(ControlEvidence.document_id == document_id)
    elif trust_article_id is not None:
        q = q.filter(ControlEvidence.trust_article_id == trust_article_id)
    else:
        q = q.filter(ControlEvidence.export_record_id == export_record_id)
    return q.order_by(ControlEvidence.id).first()


def _mirror_evidence(
    db: Session, legacy: Control, evidence: ControlEvidence, *, workspace_id: int
) -> None:
    workspace = workspace_for_legacy(db, legacy)
    if workspace is None:
        return
    item = None
    if evidence.evidence_item_id is not None:
        item = (
            db.query(EvidenceItem)
            .filter(
                EvidenceItem.id == evidence.evidence_item_id,
                EvidenceItem.workspace_id == workspace_id,
            )
            .first()
        )
    if item is None and evidence.document_id is not None:
        item = (
            db.query(EvidenceItem)
            .filter(
                EvidenceItem.workspace_id == workspace_id,
                EvidenceItem.document_id == evidence.document_id,
            )
            .order_by(EvidenceItem.id)
            .first()
        )
        if item is None:
            doc = db.query(Document).filter(Document.id == evidence.document_id).first()
            title = (doc.filename if doc is not None else None) or "document"
            item = EvidenceItem(
                workspace_id=workspace_id,
                document_id=evidence.document_id,
                source_type="document",
                title=title[:512],
            )
            db.add(item)
            db.flush()
    elif item is None and evidence.trust_article_id is not None:
        art = db.query(TrustArticle).filter(TrustArticle.id == evidence.trust_article_id).first()
        title = (art.title if art is not None else None) or "article"
        item = EvidenceItem(
            workspace_id=workspace_id,
            source_type="manual",
            title=title[:512],
        )
        db.add(item)
        db.flush()
    elif item is None and evidence.export_record_id is not None:
        rec = db.query(ExportRecord).filter(ExportRecord.id == evidence.export_record_id).first()
        title = (rec.filename if rec is not None else None) or "export"
        item = EvidenceItem(
            workspace_id=workspace_id,
            source_type="manual",
            title=title[:512],
        )
        db.add(item)
        db.flush()
    if item is None:
        return
    evidence.evidence_item_id = item.id
    link = (
        db.query(ControlEvidenceLink)
        .filter(
            ControlEvidenceLink.control_id == workspace.id,
            ControlEvidenceLink.evidence_id == item.id,
        )
        .first()
    )
    if link is None:
        db.add(
            ControlEvidenceLink(
                control_id=workspace.id,
                evidence_id=item.id,
                verified=False,
            )
        )
    db.commit()


def attach_legacy_evidence(
    db: Session,
    legacy: Control,
    *,
    document_id: int | None,
    trust_article_id: int | None,
    export_record_id: int | None,
    mirror_workspace_id: int | None = None,
) -> ContractResult:
    """Link one target. A repeat of the same target reuses the row and finishes the mirror."""
    existing = _existing_evidence(
        db,
        legacy.id,
        document_id=document_id,
        trust_article_id=trust_article_id,
        export_record_id=export_record_id,
    )
    created = existing is None
    if existing is None:
        existing = ControlEvidence(
            control_id=legacy.id,
            document_id=document_id,
            trust_article_id=trust_article_id,
            export_record_id=export_record_id,
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
    evidence_id = existing.id
    target_workspace = legacy.workspace_id if mirror_workspace_id is None else mirror_workspace_id
    try:
        _mirror_evidence(db, legacy, existing, workspace_id=target_workspace)
    except IntegrityError:
        db.rollback()
        return ContractResult(
            409,
            {},
            partial_failure=True,
            created=created,
            error={
                "contract_version": ERROR_CONTRACT_VERSION,
                "code": "control_evidence_partial_failure",
                "message": (
                    "The evidence link was saved. The canonical evidence mirror "
                    "could not be written because a foreign-key check failed."
                ),
                "retryable": True,
                "partial_failure": True,
                "evidence_id": evidence_id,
                "control_id": legacy.id,
                "steps": [
                    {"step": "legacy_evidence", "status": "persisted"},
                    {"step": "canonical_mirror", "status": "failed", "reason": "foreign_key"},
                ],
            },
            ids={"evidence_id": evidence_id},
        )
    evidence = db.query(ControlEvidence).filter(ControlEvidence.id == evidence_id).one()
    return ContractResult(200, {}, created=created, ids={"evidence": evidence})


def detach_legacy_evidence(db: Session, legacy: Control, evidence: ControlEvidence) -> None:
    workspace = workspace_for_legacy(db, legacy)
    if workspace is not None and evidence.evidence_item_id is not None:
        link = (
            db.query(ControlEvidenceLink)
            .filter(
                ControlEvidenceLink.control_id == workspace.id,
                ControlEvidenceLink.evidence_id == evidence.evidence_item_id,
            )
            .first()
        )
        if link is not None:
            db.delete(link)
    db.delete(evidence)
    db.commit()


def new_request_id() -> str:
    return uuid.uuid4().hex
