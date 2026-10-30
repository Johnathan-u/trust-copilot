"""Public vendor-response endpoint — resolves a secure link token for vendors."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Questionnaire, Question
from app.services import vendor_request_service as service

router = APIRouter(prefix="/vendor-response", tags=["vendor-response"])


@router.get("")
def get_vendor_response(
    token: str = Query(..., min_length=10, max_length=256, pattern=r"^[A-Za-z0-9_-]+$"),
    db: Session = Depends(get_db),
):
    """Public endpoint — no auth required. Resolves a secure link token."""
    vr = service.public_request(db, token)

    result: dict = {
        "status": service.status(vr),
        "message": vr.message,
        "questionnaire": None,
    }

    if vr.questionnaire_id:
        # Only expose a live questionnaire from the request's own workspace. Anything else
        # (another workspace, soft-deleted, missing) is treated as "no questionnaire".
        qnr = (
            db.query(Questionnaire)
            .filter(
                Questionnaire.id == vr.questionnaire_id,
                Questionnaire.workspace_id == vr.workspace_id,
                Questionnaire.deleted_at.is_(None),
            )
            .first()
        )
        if qnr:
            question_count = (
                db.query(func.count(Question.id))
                .filter(Question.questionnaire_id == qnr.id)
                .scalar()
            ) or 0
            result["questionnaire"] = {
                "name": qnr.filename,
                "question_count": question_count,
            }

    return result


class FinalVendorResponse(BaseModel):
    token: str = Field(min_length=10, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    response: str = Field(min_length=1, max_length=20000)

    @field_validator("response")
    @classmethod
    def validate_response(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("A valid response is required")
        return value


@router.post("/submit")
def submit_vendor_response(body: FinalVendorResponse, db: Session = Depends(get_db)):
    """Submit a final response using an active invitation; identical retries return the original receipt."""
    return service.final_submit(db, body.token, body.response)
