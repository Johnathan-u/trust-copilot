"""Connect, verify, rotate, and revoke connector credentials.

Rotate and revoke (and connect, which also writes) use ``app.core.idempotency``.
``SideEffectIdempotencyPort`` stays on TC-20-001 observation storage: ``job_effects``
needs a Job row, and the HTTP helpers commit the session.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.idempotency import (
    get as idempotency_get,
    release as idempotency_release,
    set as idempotency_set,
    try_claim as idempotency_try_claim,
)
from app.models.credential_store import CredentialStore
from app.services import credential_store_service as cs
from app.services.credential_lifecycle.probes import ProbeOutcome, probe_credential
from app.services.credential_lifecycle.scopes import (
    canonical_source,
    default_credential_type,
    least_privilege,
)
from app.services.provider_adapter.contract import (
    ObservationState,
    ProvenanceKind,
    make_observation,
)


class LifecycleNotFound(Exception):
    def __init__(self) -> None:
        super().__init__("Credential not found")


class LifecycleConflict(Exception):
    def __init__(self) -> None:
        super().__init__("Request in progress; retry with same Idempotency-Key")


def _find(
    db: Session,
    workspace_id: int,
    *,
    credential_id: int | None = None,
    source_type: str | None = None,
    credential_type: str | None = None,
    lock: bool = False,
) -> CredentialStore | None:
    query = db.query(CredentialStore).filter(CredentialStore.workspace_id == workspace_id)
    if credential_id is not None:
        query = query.filter(CredentialStore.id == credential_id)
    else:
        query = query.filter(
            CredentialStore.source_type == source_type,
            CredentialStore.credential_type == credential_type,
        )
    if lock:
        query = query.with_for_update()
    return query.order_by(CredentialStore.id.asc()).first()


def _privilege(source_type: str, action: str) -> dict:
    table = least_privilege(source_type)
    if action == "revoke":
        return {"scopes": table["revoke_scopes"], "calls": table["revoke_calls"]}
    return {"scopes": table["verify_scopes"], "calls": table["verify_calls"]}


def _with_probe(
    row: CredentialStore | None, action: str, outcome: ProbeOutcome, **fallback
) -> dict:
    if row is None:
        body = {
            "id": None,
            "status": "not_stored",
            "secret_last4": None,
            "secret_fingerprint": None,
            "credential_ref": None,
            "encryption_version": None,
            "destroyed_at": None,
        }
        body.update(fallback)
    else:
        body = cs._serialize(row)
    body["action"] = action
    body["observation"] = outcome.observation
    body["least_privilege"] = _privilege(
        body.get("source_type") or fallback.get("source_type", ""), action
    )
    return body


def _run(db: Session, key: str, producer):
    if not key:
        return producer()
    cached = idempotency_get(db, key)
    if cached:
        return cached[1]
    if not idempotency_try_claim(db, key):
        cached_again = idempotency_get(db, key)
        if cached_again:
            return cached_again[1]
        raise LifecycleConflict()
    try:
        body = producer()
    except Exception:
        db.rollback()
        idempotency_release(db, key)
        raise
    idempotency_set(db, key, 200, body)
    return body


def _probe(
    source_type: str,
    material: dict,
    *,
    action: str,
    workspace_id: int,
    credential_type: str,
    transport=None,
    aws_factory=None,
) -> ProbeOutcome:
    return probe_credential(
        source_type,
        material,
        action=action,
        workspace_id=workspace_id,
        credential_type=credential_type,
        transport=transport,
        aws_factory=aws_factory,
    )


def connect(
    db: Session,
    workspace_id: int,
    source_type: str,
    credential_type: str,
    value: str,
    *,
    extra: dict | None = None,
    rotation_interval_days: int | None = None,
    expires_at: datetime | None = None,
    idempotency_key: str = "",
    transport=None,
    aws_factory=None,
) -> dict:
    source = canonical_source(source_type)

    def producer() -> dict:
        material = {"secret": value, **(extra or {})}
        outcome = _probe(
            source,
            material,
            action="connect",
            workspace_id=workspace_id,
            credential_type=credential_type,
            transport=transport,
            aws_factory=aws_factory,
        )
        if outcome.state != ObservationState.SUCCESS.value:
            return _with_probe(
                None,
                "connect",
                outcome,
                workspace_id=workspace_id,
                source_type=source,
                credential_type=credential_type,
            )
        stored = cs.store_credential(
            db,
            workspace_id,
            source,
            credential_type,
            value,
            rotation_interval_days=rotation_interval_days,
            expires_at=expires_at,
            extra=extra,
        )
        stored["action"] = "connect"
        stored["observation"] = outcome.observation
        stored["least_privilege"] = _privilege(source, "connect")
        return stored

    return _run(db, idempotency_key, producer)


def verify(
    db: Session,
    workspace_id: int,
    *,
    credential_id: int | None = None,
    source_type: str | None = None,
    credential_type: str | None = None,
    transport=None,
    aws_factory=None,
) -> dict:
    source = canonical_source(source_type) if source_type else None
    row = _find(
        db,
        workspace_id,
        credential_id=credential_id,
        source_type=source,
        credential_type=credential_type,
    )
    if row is None or row.status != "active":
        raise LifecycleNotFound()
    material = cs.read_material(db, row)
    if material is None:
        observation, _connection = make_observation(
            provider=row.source_type,
            resource_id=f"credential-probe:{row.source_type}:verify",
            state=ObservationState.FAILURE,
            provenance_kind=ProvenanceKind.CREDENTIAL_CUSTODY,
            workspace_id=workspace_id,
            credential_type=row.credential_type,
            error_code="credential_revoked",
            safe_message="The credential was rejected by the provider.",
            note="destroyed_credential",
        )
        outcome = ProbeOutcome(
            ObservationState.FAILURE.value,
            "credential_revoked",
            observation.safe_message or "",
            observation.to_dict(),
            (),
        )
        return _with_probe(row, "verify", outcome)
    outcome = _probe(
        row.source_type,
        material,
        action="verify",
        workspace_id=workspace_id,
        credential_type=row.credential_type,
        transport=transport,
        aws_factory=aws_factory,
    )
    return _with_probe(row, "verify", outcome)


def rotate(
    db: Session,
    workspace_id: int,
    value: str,
    *,
    credential_id: int | None = None,
    source_type: str | None = None,
    credential_type: str | None = None,
    extra: dict | None = None,
    idempotency_key: str = "",
    transport=None,
    aws_factory=None,
) -> dict:
    source = canonical_source(source_type) if source_type else None

    def producer() -> dict:
        row = _find(
            db,
            workspace_id,
            credential_id=credential_id,
            source_type=source,
            credential_type=credential_type,
            lock=True,
        )
        if row is None or row.status != "active":
            raise LifecycleNotFound()
        material = {"secret": value, **(extra or {})}
        outcome = _probe(
            row.source_type,
            material,
            action="rotate",
            workspace_id=workspace_id,
            credential_type=row.credential_type,
            transport=transport,
            aws_factory=aws_factory,
        )
        if outcome.state != ObservationState.SUCCESS.value:
            return _with_probe(row, "rotate", outcome)
        cs._apply_seal(row, value, extra=extra)
        row.last_rotated_at = datetime.now(timezone.utc)
        db.flush()
        return _with_probe(row, "rotate", outcome)

    return _run(db, idempotency_key, producer)


def _revoke_outcome(row: CredentialStore) -> ProbeOutcome:
    observation, _connection = make_observation(
        provider=row.source_type,
        resource_id=f"credential-probe:{row.source_type}:revoke",
        state=ObservationState.SUCCESS,
        provenance_kind=ProvenanceKind.CREDENTIAL_CUSTODY,
        workspace_id=row.workspace_id,
        credential_type=row.credential_type,
        safe_message="The local credential was destroyed.",
        normalized_value={"action": "revoke", "destroyed": True},
        note="local_revoke",
    )
    return ProbeOutcome(
        ObservationState.SUCCESS.value,
        None,
        observation.safe_message or "",
        observation.to_dict(),
        (),
    )


def revoke(
    db: Session,
    workspace_id: int,
    *,
    credential_id: int | None = None,
    source_type: str | None = None,
    credential_type: str | None = None,
    idempotency_key: str = "",
) -> dict:
    source = canonical_source(source_type) if source_type else None

    def producer() -> dict:
        row = _find(
            db,
            workspace_id,
            credential_id=credential_id,
            source_type=source,
            credential_type=credential_type,
            lock=True,
        )
        if row is None:
            raise LifecycleNotFound()
        if row.status != "revoked" or row.encrypted_value != cs.DESTROYED:
            cs._destroy(row)
            db.flush()
        return _with_probe(row, "revoke", _revoke_outcome(row))

    return _run(db, idempotency_key, producer)


def assess_stored(
    db: Session,
    workspace_id: int,
    source_type: str,
    *,
    transport=None,
    aws_factory=None,
) -> ProbeOutcome:
    """Probe the active credential for a connector, or report that none is stored."""
    source = canonical_source(source_type)
    preferred = default_credential_type(source)
    rows = (
        db.query(CredentialStore)
        .filter(
            CredentialStore.workspace_id == workspace_id,
            CredentialStore.source_type == source,
            CredentialStore.status == "active",
        )
        .all()
    )
    rows.sort(key=lambda item: (item.credential_type != preferred, -(item.id or 0)))
    row = rows[0] if rows else None
    if row is None:
        observation, _connection = make_observation(
            provider=source,
            resource_id=f"credential-probe:{source}:verify",
            state=ObservationState.MISSING_PERMISSION,
            provenance_kind=ProvenanceKind.CREDENTIAL_CUSTODY,
            workspace_id=workspace_id,
            credential_type=preferred,
            error_code="missing_permission",
            safe_message="The credential is missing a required permission.",
            note="no_stored_credential",
        )
        return ProbeOutcome(
            ObservationState.MISSING_PERMISSION.value,
            "missing_permission",
            observation.safe_message or "",
            observation.to_dict(),
            (),
        )
    material = cs.read_material(db, row)
    if material is None:
        observation, _connection = make_observation(
            provider=source,
            resource_id=f"credential-probe:{source}:verify",
            state=ObservationState.FAILURE,
            provenance_kind=ProvenanceKind.CREDENTIAL_CUSTODY,
            workspace_id=workspace_id,
            credential_type=row.credential_type,
            error_code="credential_revoked",
            safe_message="The credential was rejected by the provider.",
            note="destroyed_credential",
        )
        return ProbeOutcome(
            ObservationState.FAILURE.value,
            "credential_revoked",
            observation.safe_message or "",
            observation.to_dict(),
            (),
        )
    return _probe(
        source,
        material,
        action="verify",
        workspace_id=workspace_id,
        credential_type=row.credential_type,
        transport=transport,
        aws_factory=aws_factory,
    )
