"""Public vendor-response endpoint — resolves a secure link token for vendors."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import VendorRequest, Questionnaire, Question

router = APIRouter(prefix="/vendor-response", tags=["vendor-response"])


@router.get("")
def get_vendor_response(
    token: str = Query(..., min_length=10),
    db: Session = Depends(get_db),
):
    """Public endpoint — no auth required. Resolves a secure link token."""
    vr = (
        db.query(VendorRequest)
        .filter(VendorRequest.link_token == token)
        .first()
    )
    if not vr:
        raise HTTPException(status_code=404, detail="This link is invalid or has expired.")

    result: dict = {
        "status": vr.status,
        "message": vr.message,
        "questionnaire": None,
    }

    if vr.questionnaire_id:
        qnr = (
            db.query(Questionnaire)
            .filter(Questionnaire.id == vr.questionnaire_id)
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
