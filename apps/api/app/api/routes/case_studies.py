"""Case study API (P0-83, TC-25-005).

Request and response fields from the original CRUD contract are unchanged.
schema_version case-study.v2 adds the consent workflow fields.
Publishing is not done by setting status on PATCH.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.auth_deps import require_can_admin, require_can_review, require_session
from app.core.database import get_db
from app.core.idempotency import get as idempotency_get
from app.core.idempotency import set as idempotency_set
from app.core.idempotency import try_claim as idempotency_try_claim
from app.services import case_study_service as cs
from app.services.case_study_service import CaseStudyError

router = APIRouter(prefix="/case-studies", tags=["case-studies"])

PRESERVED_FIELDS = (
    "id",
    "workspace_id",
    "title",
    "company_name",
    "industry",
    "company_size",
    "challenge",
    "solution",
    "results",
    "quote",
    "quote_attribution",
    "metrics",
    "status",
    "published_at",
    "created_at",
)


class FieldErrorBody(BaseModel):
    field: str
    code: str
    organization_name: str | None = None


class ConsentBody(BaseModel):
    id: int
    organization_name: str
    granted_revision: int
    consent_reference: str | None = None
    active: bool


class ResultPermissionBody(BaseModel):
    id: int
    consent_id: int
    result_key: str
    granted_revision: int
    active: bool


class CaseStudyResponse(BaseModel):
    """case-study.v2. The first fifteen content fields match the pre-consent response."""

    schema_version: str
    id: int
    workspace_id: int
    title: str
    company_name: str | None = None
    industry: str | None = None
    company_size: str | None = None
    challenge: str | None = None
    solution: str | None = None
    results: str | None = None
    quote: str | None = None
    quote_attribution: str | None = None
    metrics: dict | None = None
    status: str
    published_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    synthetic: bool
    data_basis: str
    customer_claim: bool
    publication_authorized: bool
    review_status: str
    revision: int
    quoted_organizations: list[str]
    quoted_results: list[str]
    blockers: list[FieldErrorBody]
    display_label: str
    consents: list[ConsentBody]
    result_permissions: list[ResultPermissionBody]


class CaseStudyListResponse(BaseModel):
    schema_version: str
    case_studies: list[CaseStudyResponse]


class TemplateSection(BaseModel):
    name: str
    field: str
    prompt: str


class TemplateResponse(BaseModel):
    schema_version: str
    data_basis: str
    customer_claim: bool
    synthetic: bool
    notice: str
    sections: list[TemplateSection]
    suggested_metrics: list[str]
    metrics_are_field_names_not_results: bool


class CreateCaseStudyRequest(BaseModel):
    title: str
    company_name: str | None = None
    industry: str | None = None
    company_size: str | None = None
    challenge: str | None = None
    solution: str | None = None
    results: str | None = None
    quote: str | None = None
    quote_attribution: str | None = None
    metrics: dict | None = None
    synthetic: bool | None = None
    quoted_organizations: list[str] | None = None


class UpdateCaseStudyRequest(BaseModel):
    title: str | None = None
    company_name: str | None = None
    industry: str | None = None
    company_size: str | None = None
    challenge: str | None = None
    solution: str | None = None
    results: str | None = None
    quote: str | None = None
    quote_attribution: str | None = None
    metrics: dict | None = None
    status: str | None = None
    synthetic: bool | None = None
    quoted_organizations: list[str] | None = None
    expected_revision: int | None = None


class RevisionBody(BaseModel):
    expected_revision: int


class ConsentRequest(BaseModel):
    organization_name: str
    consent_reference: str | None = None
    expected_revision: int


class ResultPermissionRequest(BaseModel):
    consent_id: int
    result_key: str
    expected_revision: int


class ReviewRequest(BaseModel):
    decision: str
    expected_revision: int


def _error_body(exc: CaseStudyError) -> dict:
    return {
        "schema_version": "api-error.v1",
        "code": exc.code,
        "message": exc.message,
        "msg": exc.message,
        "request_id": uuid.uuid4().hex,
        "retryable": exc.retryable,
        "field_errors": exc.field_errors,
    }


def _json_error(exc: CaseStudyError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": _error_body(exc)})


def _idempotency_storage_key(request: Request, workspace_id: int, case_id: int) -> str | None:
    raw = (request.headers.get("Idempotency-Key") or "").strip()
    if not raw:
        return None
    if len(raw) > 180:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    return f"case-study:{workspace_id}:{case_id}:{raw}"


def _load_cached(db: Session, key: str | None) -> JSONResponse | None:
    if not key:
        return None
    cached = idempotency_get(db, key)
    if cached:
        return JSONResponse(content=cached[1], status_code=cached[0])
    if not idempotency_try_claim(db, key):
        cached_again = idempotency_get(db, key)
        if cached_again:
            return JSONResponse(content=cached_again[1], status_code=cached_again[0])
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    return None


@router.get("/template", response_model=TemplateResponse)
async def get_template():
    return cs.get_template()


@router.get("", response_model=CaseStudyListResponse)
async def list_case_studies(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    payload = {
        "schema_version": cs.SCHEMA_VERSION,
        "case_studies": cs.list_all(db, session["workspace_id"]),
    }
    db.commit()
    return payload


@router.post("", response_model=CaseStudyResponse)
async def create_case_study(
    req: CreateCaseStudyRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
        result = cs.create(
            db,
            session["workspace_id"],
            req.title,
            **req.model_dump(exclude={"title"}),
        )
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    db.commit()
    audit_log(
        "case_study.create",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=session.get("workspace_id"),
        resource_type="case_study",
        resource_id=result["id"],
        details={"synthetic": result["synthetic"], "customer_claim": False},
    )
    return result


@router.get("/{case_id}", response_model=CaseStudyResponse)
async def get_case_study(
    case_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = cs.get(db, session["workspace_id"], case_id)
    if not result:
        raise HTTPException(status_code=404, detail="Case study not found")
    db.commit()
    return result


@router.patch("/{case_id}", response_model=CaseStudyResponse)
async def update_case_study(
    case_id: int,
    req: UpdateCaseStudyRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    updates = {key: value for key, value in req.model_dump().items() if value is not None}
    try:
        result = cs.update(db, session["workspace_id"], case_id, **updates)
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    if not result:
        raise HTTPException(status_code=404, detail="Case study not found")
    db.commit()
    return result


@router.delete("/{case_id}")
async def delete_case_study(
    case_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    if not cs.delete(db, session["workspace_id"], case_id):
        raise HTTPException(status_code=404, detail="Case study not found")
    db.commit()
    return {"deleted": True}


@router.post("/{case_id}/consents", response_model=CaseStudyResponse)
async def grant_consent(
    case_id: int,
    req: ConsentRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
        result = cs.grant_organization_consent(
            db,
            session["workspace_id"],
            case_id,
            organization_name=req.organization_name,
            consent_reference=req.consent_reference,
            actor_user_id=session.get("user_id"),
            expected_revision=req.expected_revision,
        )
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    db.commit()
    audit_log(
        "case_study.consent",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=session.get("workspace_id"),
        resource_type="case_study",
        resource_id=case_id,
        details={"revision": result["revision"]},
    )
    return result


@router.post("/{case_id}/consents/{consent_id}/revoke", response_model=CaseStudyResponse)
async def revoke_consent(
    case_id: int,
    consent_id: int,
    req: RevisionBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
        result = cs.revoke_organization_consent(
            db,
            session["workspace_id"],
            case_id,
            consent_id,
            expected_revision=req.expected_revision,
        )
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    db.commit()
    return result


@router.post("/{case_id}/result-permissions", response_model=CaseStudyResponse)
async def grant_permission(
    case_id: int,
    req: ResultPermissionRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
        result = cs.grant_result_permission(
            db,
            session["workspace_id"],
            case_id,
            consent_id=req.consent_id,
            result_key=req.result_key,
            actor_user_id=session.get("user_id"),
            expected_revision=req.expected_revision,
        )
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    db.commit()
    return result


@router.post(
    "/{case_id}/result-permissions/{permission_id}/revoke",
    response_model=CaseStudyResponse,
)
async def revoke_permission(
    case_id: int,
    permission_id: int,
    req: RevisionBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
        result = cs.revoke_result_permission(
            db,
            session["workspace_id"],
            case_id,
            permission_id,
            expected_revision=req.expected_revision,
        )
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    db.commit()
    return result


@router.post("/{case_id}/submit-review", response_model=CaseStudyResponse)
async def submit_review(
    case_id: int,
    req: RevisionBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
        result = cs.submit_for_review(
            db,
            session["workspace_id"],
            case_id,
            expected_revision=req.expected_revision,
        )
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    db.commit()
    return result


@router.post("/{case_id}/review", response_model=CaseStudyResponse)
async def review_case_study(
    case_id: int,
    req: ReviewRequest,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    try:
        result = cs.record_review(
            db,
            session["workspace_id"],
            case_id,
            decision=req.decision,
            actor_user_id=session.get("user_id"),
            expected_revision=req.expected_revision,
        )
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    db.commit()
    audit_log(
        "case_study.review",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=session.get("workspace_id"),
        resource_type="case_study",
        resource_id=case_id,
        details={"decision": req.decision, "review_status": result["review_status"]},
    )
    return result


@router.post("/{case_id}/publish", response_model=CaseStudyResponse)
async def publish_case_study(
    case_id: int,
    req: RevisionBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    key = _idempotency_storage_key(request, session["workspace_id"], case_id)
    cached = _load_cached(db, key)
    if cached is not None:
        return cached
    try:
        result = cs.publish(
            db,
            session["workspace_id"],
            case_id,
            expected_revision=req.expected_revision,
        )
    except CaseStudyError as exc:
        db.rollback()
        body = {"detail": _error_body(exc)}
        if key:
            idempotency_set(db, key, exc.status_code, body)
        return JSONResponse(status_code=exc.status_code, content=body)
    db.commit()
    if key:
        idempotency_set(db, key, 200, result)
    audit_log(
        "case_study.publish",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=session.get("workspace_id"),
        resource_type="case_study",
        resource_id=case_id,
        details={
            "customer_claim": result["customer_claim"],
            "synthetic": result["synthetic"],
            "data_basis": result["data_basis"],
            "revision": result["revision"],
        },
    )
    return result


@router.post("/{case_id}/withdraw", response_model=CaseStudyResponse)
async def withdraw_case_study(
    case_id: int,
    req: RevisionBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    try:
        result = cs.withdraw(
            db,
            session["workspace_id"],
            case_id,
            expected_revision=req.expected_revision,
        )
    except CaseStudyError as exc:
        db.rollback()
        return _json_error(exc)
    db.commit()
    audit_log(
        "case_study.withdraw",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=session.get("workspace_id"),
        resource_type="case_study",
        resource_id=case_id,
        details={"customer_claim": result["customer_claim"], "revision": result["revision"]},
    )
    return result
