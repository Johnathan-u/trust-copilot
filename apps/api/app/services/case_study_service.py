"""Case study authoring and consent-backed publication (P0-83, TC-25-005).

Draft, review, and publish. A row is a customer claim only when it is not
synthetic, review has approved the current revision, and every quoted
organization has an active consent that permits every quoted result.
Synthetic rows stay labeled synthetic_example and never become a customer claim.
No seed path inserts a case study.
"""

import json
import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.case_study import (
    DATA_BASIS_CONSENTED,
    DATA_BASIS_SYNTHETIC,
    DATA_BASIS_TEMPLATE,
    DATA_BASIS_UNVERIFIED,
    METRIC_PREFIX,
    RESULT_NARRATIVE,
    RESULT_QUOTE,
    REVIEW_APPROVED,
    REVIEW_CHANGES,
    REVIEW_NONE,
    REVIEW_PENDING,
    SCHEMA_VERSION,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    STATUS_PUBLISHED,
    CaseStudy,
    CaseStudyOrganizationConsent,
    CaseStudyResultPermission,
)

_MAX_TEXT = 20000
_MAX_ORGS = 20
_MAX_METRICS = 50
_METRIC_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_CONTENT_FIELDS = (
    "title",
    "company_name",
    "industry",
    "company_size",
    "challenge",
    "solution",
    "results",
    "quote",
    "quote_attribution",
    "synthetic",
)

TEMPLATE = {
    "schema_version": SCHEMA_VERSION,
    "data_basis": DATA_BASIS_TEMPLATE,
    "customer_claim": False,
    "synthetic": False,
    "notice": "Blank authoring template. It contains no customer, quote, or result.",
    "sections": [
        {
            "name": "Organization background",
            "field": "company_name",
            "prompt": "Name of the quoted organization, only after that organization has consented. This template names nobody.",
        },
        {
            "name": "The challenge",
            "field": "challenge",
            "prompt": "Blank field for the problem statement. This template does not describe a real engagement.",
        },
        {
            "name": "The solution",
            "field": "solution",
            "prompt": "Blank field for what was deployed. This template is not evidence of a deployment.",
        },
        {
            "name": "The results",
            "field": "results",
            "prompt": "Blank field. Each quoted result needs its own permission before publication.",
        },
        {
            "name": "Quote",
            "field": "quote",
            "prompt": "Blank field. A quote needs organization consent. This template contains no quote.",
        },
    ],
    "suggested_metrics": [
        "questionnaires_completed",
        "hours_saved",
        "avg_completion_time_minutes",
        "accuracy_rate_pct",
        "deals_unblocked",
        "deal_value_unblocked",
    ],
    "metrics_are_field_names_not_results": True,
}


class CaseStudyError(Exception):
    """Safe, versioned failure for the case study workflow."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        retryable: bool = False,
        field_errors: list | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.field_errors = field_errors or []


def get_template() -> dict:
    return TEMPLATE


def create(db: Session, workspace_id: int, title: str, **fields) -> dict:
    cleaned_title = _require_title(title)
    row = CaseStudy(
        workspace_id=workspace_id,
        title=cleaned_title,
        status=STATUS_DRAFT,
        synthetic=False,
        data_basis=DATA_BASIS_UNVERIFIED,
        customer_claim=False,
        publication_authorized=False,
        review_status=REVIEW_NONE,
        revision=1,
        schema_version=SCHEMA_VERSION,
    )
    _apply_content(row, fields, creating=True)
    db.add(row)
    db.flush()
    reconcile(db, row)
    return _serialize(db, row)


def list_all(db: Session, workspace_id: int) -> list[dict]:
    rows = (
        db.query(CaseStudy)
        .filter(CaseStudy.workspace_id == workspace_id)
        .order_by(CaseStudy.created_at.desc(), CaseStudy.id.desc())
        .all()
    )
    for row in rows:
        reconcile(db, row)
    return [_serialize(db, row) for row in rows]


def get(db: Session, workspace_id: int, case_id: int) -> dict | None:
    row = _get_row(db, workspace_id, case_id)
    if not row:
        return None
    reconcile(db, row)
    return _serialize(db, row)


def update(db: Session, workspace_id: int, case_id: int, **updates) -> dict | None:
    row = _get_row(db, workspace_id, case_id)
    if not row:
        return None
    if "expected_revision" in updates and updates["expected_revision"] is not None:
        _require_revision(row, updates["expected_revision"])
    _reject_status_bypass(row, updates.get("status"))
    changed = _apply_content(row, updates, creating=False)
    if changed:
        _invalidate_publication(row)
        row.revision = int(row.revision or 1) + 1
    reconcile(db, row)
    db.flush()
    return _serialize(db, row)


def delete(db: Session, workspace_id: int, case_id: int) -> bool:
    row = _get_row(db, workspace_id, case_id)
    if not row:
        return False
    db.delete(row)
    db.flush()
    return True


def grant_organization_consent(
    db: Session,
    workspace_id: int,
    case_id: int,
    *,
    organization_name: str,
    consent_reference: str | None,
    actor_user_id: int | None,
    expected_revision: int,
) -> dict:
    row = _require_row(db, workspace_id, case_id)
    _require_revision(row, expected_revision)
    name = _require_quoted_org(row, organization_name)
    reference = _clean_reference(consent_reference)
    existing = _active_consent_for(db, row, name)
    if existing and existing.granted_revision == row.revision and existing.consent_granted:
        existing.consent_reference = reference
        db.flush()
        return _serialize(db, row)
    if existing:
        existing.revoked_at = _now()
        db.flush()
    consent = CaseStudyOrganizationConsent(
        workspace_id=row.workspace_id,
        case_study_id=row.id,
        organization_name=name,
        consent_reference=reference,
        consent_granted=True,
        granted_revision=row.revision,
        granted_by_user_id=actor_user_id,
    )
    db.add(consent)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise CaseStudyError(
            "foreign_reference",
            "Organization consent could not be stored for this case study.",
            status_code=422,
            field_errors=[
                {
                    "field": "organization_name",
                    "code": "foreign_reference",
                    "organization_name": name,
                }
            ],
        ) from exc
    reconcile(db, row)
    return _serialize(db, row)


def revoke_organization_consent(
    db: Session,
    workspace_id: int,
    case_id: int,
    consent_id: int,
    *,
    expected_revision: int,
) -> dict:
    row = _require_row(db, workspace_id, case_id)
    _require_revision(row, expected_revision)
    consent = _consent_for_case(db, row, consent_id)
    if consent.revoked_at is None:
        consent.revoked_at = _now()
        db.flush()
    reconcile(db, row)
    return _serialize(db, row)


def grant_result_permission(
    db: Session,
    workspace_id: int,
    case_id: int,
    *,
    consent_id: int,
    result_key: str,
    actor_user_id: int | None,
    expected_revision: int,
) -> dict:
    row = _require_row(db, workspace_id, case_id)
    _require_revision(row, expected_revision)
    key = _require_quoted_result(row, result_key)
    consent = _consent_for_case(db, row, consent_id)
    if consent.revoked_at is not None or not consent.consent_granted:
        raise _gap_error(
            "consent_inactive",
            "Result permission requires an active organization consent.",
            field="consent_id",
            organization_name=consent.organization_name,
        )
    if consent.granted_revision != row.revision:
        raise _gap_error(
            "consent_stale",
            "Organization consent does not cover the current revision.",
            field="consent_id",
            organization_name=consent.organization_name,
        )
    existing = (
        db.query(CaseStudyResultPermission)
        .filter(
            CaseStudyResultPermission.consent_id == consent.id,
            CaseStudyResultPermission.result_key == key,
            CaseStudyResultPermission.revoked_at.is_(None),
        )
        .first()
    )
    if existing and existing.granted_revision == row.revision and existing.permitted:
        return _serialize(db, row)
    if existing:
        existing.revoked_at = _now()
        db.flush()
    permission = CaseStudyResultPermission(
        workspace_id=row.workspace_id,
        case_study_id=row.id,
        consent_id=consent.id,
        result_key=key,
        permitted=True,
        granted_revision=row.revision,
        granted_by_user_id=actor_user_id,
    )
    db.add(permission)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise CaseStudyError(
            "foreign_reference",
            "Result permission does not match this case study and consent.",
            status_code=422,
            field_errors=[
                {
                    "field": key,
                    "code": "foreign_reference",
                    "organization_name": consent.organization_name,
                }
            ],
        ) from exc
    reconcile(db, row)
    return _serialize(db, row)


def revoke_result_permission(
    db: Session,
    workspace_id: int,
    case_id: int,
    permission_id: int,
    *,
    expected_revision: int,
) -> dict:
    row = _require_row(db, workspace_id, case_id)
    _require_revision(row, expected_revision)
    permission = (
        db.query(CaseStudyResultPermission)
        .filter(
            CaseStudyResultPermission.id == permission_id,
            CaseStudyResultPermission.case_study_id == row.id,
            CaseStudyResultPermission.workspace_id == row.workspace_id,
        )
        .first()
    )
    if not permission:
        raise CaseStudyError(
            "foreign_reference",
            "Result permission was not found on this case study.",
            status_code=422,
            field_errors=[
                {"field": "permission_id", "code": "foreign_reference", "organization_name": None}
            ],
        )
    if permission.revoked_at is None:
        permission.revoked_at = _now()
        db.flush()
    reconcile(db, row)
    return _serialize(db, row)


def submit_for_review(
    db: Session,
    workspace_id: int,
    case_id: int,
    *,
    expected_revision: int,
) -> dict:
    row = _require_row(db, workspace_id, case_id)
    _require_revision(row, expected_revision)
    if row.status != STATUS_DRAFT:
        raise CaseStudyError(
            "invalid_state",
            "Only a draft can be submitted for review.",
            status_code=409,
        )
    row.status = STATUS_IN_REVIEW
    row.review_status = REVIEW_PENDING
    row.publication_authorized = False
    row.customer_claim = False
    db.flush()
    reconcile(db, row)
    return _serialize(db, row)


def record_review(
    db: Session,
    workspace_id: int,
    case_id: int,
    *,
    decision: str,
    actor_user_id: int | None,
    expected_revision: int,
) -> dict:
    row = _require_row(db, workspace_id, case_id)
    _require_revision(row, expected_revision)
    if row.status != STATUS_IN_REVIEW:
        raise CaseStudyError(
            "invalid_state",
            "Review is only available while the case study is in review.",
            status_code=409,
        )
    if decision == "approve":
        row.review_status = REVIEW_APPROVED
    elif decision == "request_changes":
        row.review_status = REVIEW_CHANGES
        row.status = STATUS_DRAFT
        row.publication_authorized = False
        row.customer_claim = False
    else:
        raise CaseStudyError(
            "invalid_decision",
            "Review decision must be approve or request_changes.",
            status_code=422,
            field_errors=[
                {"field": "decision", "code": "invalid_decision", "organization_name": None}
            ],
        )
    row.reviewed_by_user_id = actor_user_id
    row.reviewed_at = _now()
    db.flush()
    reconcile(db, row)
    return _serialize(db, row)


def publish(
    db: Session,
    workspace_id: int,
    case_id: int,
    *,
    expected_revision: int,
) -> dict:
    row = _require_row(db, workspace_id, case_id)
    _require_revision(row, expected_revision)
    reconcile(db, row)
    gaps = consent_gaps(db, row)
    if row.status == STATUS_PUBLISHED and row.publication_authorized and not gaps:
        return _serialize(db, row)
    if row.status != STATUS_IN_REVIEW or row.review_status != REVIEW_APPROVED:
        raise CaseStudyError(
            "review_required",
            "Publish requires an approved review of the current revision.",
            status_code=409,
        )
    if gaps:
        raise CaseStudyError(
            "consent_incomplete",
            "Publication blocked until every quoted organization has consented and permitted every quoted result.",
            status_code=409,
            field_errors=gaps,
        )
    row.status = STATUS_PUBLISHED
    row.publication_authorized = True
    if row.published_at is None:
        row.published_at = _now()
    db.flush()
    reconcile(db, row)
    return _serialize(db, row)


def withdraw(
    db: Session,
    workspace_id: int,
    case_id: int,
    *,
    expected_revision: int,
) -> dict:
    row = _require_row(db, workspace_id, case_id)
    _require_revision(row, expected_revision)
    if row.status == STATUS_PUBLISHED:
        row.revision = int(row.revision or 1) + 1
        _invalidate_publication(row)
        db.flush()
    reconcile(db, row)
    return _serialize(db, row)


def consent_gaps(db: Session, row: CaseStudy) -> list[dict]:
    """Missing organization consents or result permissions for the current revision."""
    gaps: list[dict] = []
    if _json_broken(row.quoted_organizations_json):
        gaps.append(
            {
                "field": "quoted_organizations",
                "code": "quoted_organizations_unreadable",
                "organization_name": None,
            }
        )
    metrics, metrics_broken = _metrics(row)
    if metrics_broken:
        gaps.append(
            {"field": "metrics", "code": "metrics_unreadable", "organization_name": None}
        )
    orgs = quoted_organizations(row)
    results = quoted_result_keys(row, metrics)
    if results and not orgs:
        gaps.append(
            {
                "field": "company_name",
                "code": "quoted_result_without_organization",
                "organization_name": None,
            }
        )
    consents = {
        item.organization_name: item
        for item in _active_consents(db, row)
        if item.consent_granted and item.granted_revision == row.revision
    }
    permissions = [
        item
        for item in _active_permissions(db, row)
        if item.permitted and item.granted_revision == row.revision
    ]
    for org in orgs:
        consent = consents.get(org)
        if consent is None:
            gaps.append(
                {
                    "field": "organization",
                    "code": "organization_consent_missing",
                    "organization_name": org,
                }
            )
            for key in results:
                gaps.append(
                    {
                        "field": key,
                        "code": "result_permission_missing",
                        "organization_name": org,
                    }
                )
            continue
        covered = {
            item.result_key
            for item in permissions
            if item.consent_id == consent.id
        }
        for key in results:
            if key not in covered:
                gaps.append(
                    {
                        "field": key,
                        "code": "result_permission_missing",
                        "organization_name": org,
                    }
                )
    return gaps


def reconcile(db: Session, row: CaseStudy) -> None:
    """Make stored claim flags match current consent. Invalid publications are withdrawn."""
    gaps = consent_gaps(db, row)
    if row.status == STATUS_PUBLISHED and gaps:
        row.publication_authorized = False
        row.published_at = None
        row.status = STATUS_IN_REVIEW if row.review_status == REVIEW_APPROVED else STATUS_DRAFT
    claim = _derived_customer_claim(db, row)
    basis = _derived_data_basis(row, claim)
    row.customer_claim = claim
    row.data_basis = basis
    if row.synthetic:
        row.customer_claim = False
        row.data_basis = DATA_BASIS_SYNTHETIC
    db.flush()


def quoted_organizations(row: CaseStudy) -> list[str]:
    names: list[str] = []
    primary = _clean_name(row.company_name)
    if primary:
        names.append(primary)
    for extra in _extra_organizations(row):
        if extra not in names:
            names.append(extra)
    return names


def quoted_result_keys(row: CaseStudy, metrics: dict | None = None) -> list[str]:
    keys: list[str] = []
    if _clean_text(row.quote):
        keys.append(RESULT_QUOTE)
    if _clean_text(row.results):
        keys.append(RESULT_NARRATIVE)
    parsed = metrics
    if parsed is None:
        parsed, broken = _metrics(row)
        if broken:
            parsed = {}
    for key in sorted((parsed or {})):
        if _METRIC_KEY.match(str(key)):
            token = f"{METRIC_PREFIX}{key}"
            if token not in keys:
                keys.append(token)
    return keys


def _derived_customer_claim(db: Session, row: CaseStudy) -> bool:
    if row.synthetic or row.status != STATUS_PUBLISHED or not row.publication_authorized:
        return False
    if row.review_status != REVIEW_APPROVED:
        return False
    if not quoted_organizations(row):
        return False
    if consent_gaps(db, row):
        return False
    return True


def _derived_data_basis(row: CaseStudy, claim: bool) -> str:
    if row.synthetic:
        return DATA_BASIS_SYNTHETIC
    if claim:
        return DATA_BASIS_CONSENTED
    return DATA_BASIS_UNVERIFIED


def display_label(*, customer_claim: bool, synthetic: bool, data_basis: str) -> str:
    if customer_claim and not synthetic and data_basis == DATA_BASIS_CONSENTED:
        return "Consented publication"
    if synthetic or data_basis == DATA_BASIS_SYNTHETIC:
        return "Synthetic example. Not a customer claim."
    return "Not a customer claim."


def _serialize(db: Session, row: CaseStudy) -> dict:
    metrics, _broken = _metrics(row)
    claim = bool(row.customer_claim) and _derived_customer_claim(db, row)
    basis = DATA_BASIS_SYNTHETIC if row.synthetic else (
        DATA_BASIS_CONSENTED if claim else DATA_BASIS_UNVERIFIED
    )
    orgs = quoted_organizations(row)
    results = quoted_result_keys(row, metrics)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": row.id,
        "workspace_id": row.workspace_id,
        "title": row.title,
        "company_name": row.company_name,
        "industry": row.industry,
        "company_size": row.company_size,
        "challenge": row.challenge,
        "solution": row.solution,
        "results": row.results,
        "quote": row.quote,
        "quote_attribution": row.quote_attribution,
        "metrics": metrics,
        "status": row.status,
        "published_at": _iso(row.published_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "synthetic": bool(row.synthetic),
        "data_basis": basis,
        "customer_claim": claim,
        "publication_authorized": bool(row.publication_authorized) and not consent_gaps(db, row),
        "review_status": row.review_status,
        "revision": int(row.revision or 1),
        "quoted_organizations": orgs,
        "quoted_results": results,
        "blockers": consent_gaps(db, row) if not claim else [],
        "display_label": display_label(customer_claim=claim, synthetic=bool(row.synthetic), data_basis=basis),
        "consents": [
            {
                "id": item.id,
                "organization_name": item.organization_name,
                "granted_revision": item.granted_revision,
                "consent_reference": item.consent_reference,
                "active": item.revoked_at is None and item.consent_granted,
            }
            for item in _consents(db, row)
        ],
        "result_permissions": [
            {
                "id": item.id,
                "consent_id": item.consent_id,
                "result_key": item.result_key,
                "granted_revision": item.granted_revision,
                "active": item.revoked_at is None and item.permitted,
            }
            for item in _permissions(db, row)
        ],
    }


def _apply_content(row: CaseStudy, fields: dict, *, creating: bool) -> bool:
    changed = False
    if "synthetic" in fields and fields["synthetic"] is not None:
        synthetic = bool(fields["synthetic"])
        if bool(row.synthetic) != synthetic:
            row.synthetic = synthetic
            if not creating:
                changed = True
    for key in (
        "company_name",
        "industry",
        "company_size",
        "challenge",
        "solution",
        "results",
        "quote",
        "quote_attribution",
    ):
        if key not in fields or fields[key] is None:
            continue
        value = _bound_text(fields[key], key)
        if key == "company_name":
            value = _clean_name(value)
        if creating or getattr(row, key) != value:
            setattr(row, key, value)
            if not creating:
                changed = True
    if "title" in fields and fields["title"] is not None and not creating:
        title = _require_title(fields["title"])
        if title != row.title:
            row.title = title
            changed = True
    if "quoted_organizations" in fields and fields["quoted_organizations"] is not None:
        extra = _normalize_extra_orgs(fields["quoted_organizations"], row.company_name)
        encoded = json.dumps(extra)
        if creating:
            row.quoted_organizations_json = encoded
        elif (row.quoted_organizations_json or "[]") != encoded:
            row.quoted_organizations_json = encoded
            changed = True
    if "metrics" in fields and fields["metrics"] is not None:
        cleaned = _normalize_metrics(fields["metrics"])
        encoded = json.dumps(cleaned)
        if creating:
            row.metrics_json = encoded
        elif (row.metrics_json or "null") != encoded:
            row.metrics_json = encoded
            changed = True
    if row.synthetic:
        row.data_basis = DATA_BASIS_SYNTHETIC
        row.customer_claim = False
    return changed


def _invalidate_publication(row: CaseStudy) -> None:
    row.status = STATUS_DRAFT
    row.review_status = REVIEW_NONE
    row.publication_authorized = False
    row.published_at = None
    row.customer_claim = False
    row.reviewed_by_user_id = None
    row.reviewed_at = None
    if row.synthetic:
        row.data_basis = DATA_BASIS_SYNTHETIC
    else:
        row.data_basis = DATA_BASIS_UNVERIFIED


def _reject_status_bypass(row: CaseStudy, status: str | None) -> None:
    if status is None or status == row.status:
        return
    if status == STATUS_PUBLISHED:
        raise CaseStudyError(
            "publish_requires_workflow",
            "Publishing requires the review and consent workflow.",
            status_code=409,
        )
    if status == STATUS_IN_REVIEW:
        raise CaseStudyError(
            "review_requires_workflow",
            "Submit the draft for review instead of setting the status directly.",
            status_code=409,
        )
    raise CaseStudyError(
        "invalid_state",
        "Status changes go through submit, review, publish, or withdraw.",
        status_code=409,
    )


def _require_revision(row: CaseStudy, expected: int | None) -> None:
    if expected is None:
        raise CaseStudyError(
            "revision_required",
            "expected_revision is required.",
            status_code=422,
            retryable=True,
            field_errors=[
                {"field": "expected_revision", "code": "revision_required", "organization_name": None}
            ],
        )
    if int(expected) != int(row.revision or 1):
        raise CaseStudyError(
            "revision_conflict",
            "The case study changed. Reload it and retry.",
            status_code=409,
            retryable=True,
            field_errors=[
                {"field": "expected_revision", "code": "revision_conflict", "organization_name": None}
            ],
        )


def _require_row(db: Session, workspace_id: int, case_id: int) -> CaseStudy:
    row = _get_row(db, workspace_id, case_id)
    if not row:
        raise CaseStudyError(
            "not_found",
            "Case study not found.",
            status_code=404,
        )
    return row


def _get_row(db: Session, workspace_id: int, case_id: int) -> CaseStudy | None:
    return (
        db.query(CaseStudy)
        .filter(CaseStudy.id == case_id, CaseStudy.workspace_id == workspace_id)
        .first()
    )


def _require_quoted_org(row: CaseStudy, organization_name: str) -> str:
    name = _clean_name(organization_name)
    if not name or name not in quoted_organizations(row):
        raise CaseStudyError(
            "organization_not_quoted",
            "Consent must name an organization quoted on this case study.",
            status_code=422,
            field_errors=[
                {
                    "field": "organization_name",
                    "code": "organization_not_quoted",
                    "organization_name": name,
                }
            ],
        )
    return name


def _require_quoted_result(row: CaseStudy, result_key: str) -> str:
    key = (result_key or "").strip()
    if key not in quoted_result_keys(row):
        raise CaseStudyError(
            "result_not_quoted",
            "Permission must name a result quoted on this case study.",
            status_code=422,
            field_errors=[
                {"field": key or "result_key", "code": "result_not_quoted", "organization_name": None}
            ],
        )
    return key


def _consent_for_case(db: Session, row: CaseStudy, consent_id: int) -> CaseStudyOrganizationConsent:
    consent = (
        db.query(CaseStudyOrganizationConsent)
        .filter(
            CaseStudyOrganizationConsent.id == consent_id,
            CaseStudyOrganizationConsent.case_study_id == row.id,
            CaseStudyOrganizationConsent.workspace_id == row.workspace_id,
        )
        .first()
    )
    if not consent:
        raise CaseStudyError(
            "foreign_reference",
            "Consent must belong to this case study and workspace.",
            status_code=422,
            field_errors=[
                {"field": "consent_id", "code": "foreign_reference", "organization_name": None}
            ],
        )
    return consent


def _active_consent_for(db: Session, row: CaseStudy, name: str) -> CaseStudyOrganizationConsent | None:
    return (
        db.query(CaseStudyOrganizationConsent)
        .filter(
            CaseStudyOrganizationConsent.case_study_id == row.id,
            CaseStudyOrganizationConsent.workspace_id == row.workspace_id,
            CaseStudyOrganizationConsent.organization_name == name,
            CaseStudyOrganizationConsent.revoked_at.is_(None),
        )
        .first()
    )


def _active_consents(db: Session, row: CaseStudy) -> list[CaseStudyOrganizationConsent]:
    return (
        db.query(CaseStudyOrganizationConsent)
        .filter(
            CaseStudyOrganizationConsent.case_study_id == row.id,
            CaseStudyOrganizationConsent.workspace_id == row.workspace_id,
            CaseStudyOrganizationConsent.revoked_at.is_(None),
        )
        .all()
    )


def _consents(db: Session, row: CaseStudy) -> list[CaseStudyOrganizationConsent]:
    return (
        db.query(CaseStudyOrganizationConsent)
        .filter(
            CaseStudyOrganizationConsent.case_study_id == row.id,
            CaseStudyOrganizationConsent.workspace_id == row.workspace_id,
        )
        .order_by(CaseStudyOrganizationConsent.id.asc())
        .all()
    )


def _active_permissions(db: Session, row: CaseStudy) -> list[CaseStudyResultPermission]:
    return (
        db.query(CaseStudyResultPermission)
        .filter(
            CaseStudyResultPermission.case_study_id == row.id,
            CaseStudyResultPermission.workspace_id == row.workspace_id,
            CaseStudyResultPermission.revoked_at.is_(None),
        )
        .all()
    )


def _permissions(db: Session, row: CaseStudy) -> list[CaseStudyResultPermission]:
    return (
        db.query(CaseStudyResultPermission)
        .filter(
            CaseStudyResultPermission.case_study_id == row.id,
            CaseStudyResultPermission.workspace_id == row.workspace_id,
        )
        .order_by(CaseStudyResultPermission.id.asc())
        .all()
    )


def _normalize_metrics(value: dict) -> dict:
    if not isinstance(value, dict):
        raise CaseStudyError(
            "invalid_metrics",
            "Metrics must be an object of field names.",
            status_code=422,
            field_errors=[{"field": "metrics", "code": "invalid_metrics", "organization_name": None}],
        )
    if len(value) > _MAX_METRICS:
        raise CaseStudyError(
            "invalid_metrics",
            "Too many metric fields.",
            status_code=422,
            field_errors=[{"field": "metrics", "code": "invalid_metrics", "organization_name": None}],
        )
    cleaned: dict = {}
    for key, item in value.items():
        token = str(key).strip()
        if not _METRIC_KEY.match(token):
            raise CaseStudyError(
                "invalid_metrics",
                "Metric field names must be short identifiers.",
                status_code=422,
                field_errors=[
                    {"field": "metrics", "code": "invalid_metrics", "organization_name": None}
                ],
            )
        if isinstance(item, str):
            cleaned[token] = item.strip()[:_MAX_TEXT]
        elif isinstance(item, (int, float, bool)) or item is None:
            cleaned[token] = item
        else:
            raise CaseStudyError(
                "invalid_metrics",
                "Metric values must be text, numbers, or booleans.",
                status_code=422,
                field_errors=[
                    {"field": "metrics", "code": "invalid_metrics", "organization_name": None}
                ],
            )
    return cleaned


def _normalize_extra_orgs(value, company_name: str | None) -> list[str]:
    if not isinstance(value, list):
        raise CaseStudyError(
            "invalid_organizations",
            "Quoted organizations must be a list of names.",
            status_code=422,
            field_errors=[
                {
                    "field": "quoted_organizations",
                    "code": "invalid_organizations",
                    "organization_name": None,
                }
            ],
        )
    if len(value) > _MAX_ORGS:
        raise CaseStudyError(
            "invalid_organizations",
            "Too many quoted organizations.",
            status_code=422,
            field_errors=[
                {
                    "field": "quoted_organizations",
                    "code": "invalid_organizations",
                    "organization_name": None,
                }
            ],
        )
    primary = _clean_name(company_name)
    names: list[str] = []
    for item in value:
        name = _clean_name(item if isinstance(item, str) else "")
        if not name or name == primary or name in names:
            continue
        names.append(name)
    return names


def _extra_organizations(row: CaseStudy) -> list[str]:
    if not row.quoted_organizations_json:
        return []
    if _json_broken(row.quoted_organizations_json):
        return []
    try:
        parsed = json.loads(row.quoted_organizations_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    names: list[str] = []
    for item in parsed:
        name = _clean_name(item if isinstance(item, str) else "")
        if name and name not in names:
            names.append(name)
    return names


def _metrics(row: CaseStudy) -> tuple[dict | None, bool]:
    if not row.metrics_json:
        return None, False
    try:
        parsed = json.loads(row.metrics_json)
    except json.JSONDecodeError:
        return None, True
    if not isinstance(parsed, dict):
        return None, True
    return parsed, False


def _json_broken(raw: str | None) -> bool:
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return True
    return not isinstance(parsed, list)


def _gap_error(code: str, message: str, *, field: str, organization_name: str | None) -> CaseStudyError:
    return CaseStudyError(
        code,
        message,
        status_code=409,
        field_errors=[
            {"field": field, "code": code, "organization_name": organization_name}
        ],
    )


def _require_title(title: str) -> str:
    cleaned = _clean_text(title)
    if not cleaned:
        raise CaseStudyError(
            "invalid_title",
            "Title is required.",
            status_code=422,
            field_errors=[{"field": "title", "code": "invalid_title", "organization_name": None}],
        )
    if len(cleaned) > 512:
        raise CaseStudyError(
            "invalid_title",
            "Title is too long.",
            status_code=422,
            field_errors=[{"field": "title", "code": "invalid_title", "organization_name": None}],
        )
    return cleaned


def _bound_text(value, field: str):
    if value is None:
        return None
    if not isinstance(value, str):
        raise CaseStudyError(
            "invalid_text",
            "Text fields must be strings.",
            status_code=422,
            field_errors=[{"field": field, "code": "invalid_text", "organization_name": None}],
        )
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > _MAX_TEXT:
        raise CaseStudyError(
            "invalid_text",
            "Text field is too long.",
            status_code=422,
            field_errors=[{"field": field, "code": "invalid_text", "organization_name": None}],
        )
    return stripped


def _clean_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _clean_name(value) -> str | None:
    cleaned = _clean_text(value)
    if cleaned and len(cleaned) > 255:
        raise CaseStudyError(
            "invalid_organizations",
            "Organization name is too long.",
            status_code=422,
            field_errors=[
                {
                    "field": "organization_name",
                    "code": "invalid_organizations",
                    "organization_name": None,
                }
            ],
        )
    return cleaned


def _clean_reference(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CaseStudyError(
            "invalid_reference",
            "Consent reference must be text.",
            status_code=422,
            field_errors=[
                {"field": "consent_reference", "code": "invalid_reference", "organization_name": None}
            ],
        )
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > 255:
        raise CaseStudyError(
            "invalid_reference",
            "Consent reference is too long.",
            status_code=422,
            field_errors=[
                {"field": "consent_reference", "code": "invalid_reference", "organization_name": None}
            ],
        )
    return stripped


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)
