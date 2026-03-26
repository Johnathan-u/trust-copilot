"""Answer approval workflow API (P1-72)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review, require_session
from app.core.database import get_db
from app.services import answer_approval_service as svc

router = APIRouter(prefix="/answer-approval", tags=["answer-approval"])


class AssignBody(BaseModel):
    golden_answer_id: int
    user_id: int


class ReviewActionBody(BaseModel):
    comment: str | None = None


class BulkApproveBody(BaseModel):
    golden_answer_ids: list[int]


@router.post("/assign-owner")
async def assign_owner(body: AssignBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.assign_owner(db, body.golden_answer_id, body.user_id, session.get("user_id"))
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/assign-reviewer")
async def assign_reviewer(body: AssignBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.assign_reviewer(db, body.golden_answer_id, body.user_id, session.get("user_id"))
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/{ga_id}/submit")
async def submit_for_review(ga_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    result = svc.submit_for_review(db, ga_id, session.get("user_id"))
    if not result:
        raise HTTPException(status_code=404)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.post("/{ga_id}/approve")
async def approve(ga_id: int, body: ReviewActionBody = ReviewActionBody(), session: dict = Depends(require_can_review), db: Session = Depends(get_db)):
    result = svc.approve_answer(db, ga_id, session.get("user_id"), body.comment)
    if not result:
        raise HTTPException(status_code=404)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.post("/{ga_id}/reject")
async def reject(ga_id: int, body: ReviewActionBody = ReviewActionBody(), session: dict = Depends(require_can_review), db: Session = Depends(get_db)):
    result = svc.reject_answer(db, ga_id, session.get("user_id"), body.comment)
    if not result:
        raise HTTPException(status_code=404)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.post("/{ga_id}/request-changes")
async def request_changes(ga_id: int, body: ReviewActionBody, session: dict = Depends(require_can_review), db: Session = Depends(get_db)):
    result = svc.request_changes(db, ga_id, session.get("user_id"), body.comment)
    if not result:
        raise HTTPException(status_code=404)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.get("/queue")
async def review_queue(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"queue": svc.get_review_queue(db, session["workspace_id"])}


@router.get("/overdue")
async def overdue(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    return {"overdue": svc.get_overdue_reviews(db, session["workspace_id"])}


@router.post("/bulk-approve")
async def bulk_approve(body: BulkApproveBody, session: dict = Depends(require_can_review), db: Session = Depends(get_db)):
    result = svc.bulk_approve(db, body.golden_answer_ids, session.get("user_id"))
    db.commit()
    return result


@router.get("/{ga_id}/history")
async def history(ga_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"events": svc.get_approval_history(db, ga_id)}
