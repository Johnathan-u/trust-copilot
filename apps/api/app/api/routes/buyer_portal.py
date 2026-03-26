"""Buyer portal admin + public token routes (E4-20..E4-24)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.models.buyer_portal import BuyerPortal
from app.services import buyer_portal_service as bps

router = APIRouter(prefix="/buyer-portal", tags=["buyer-portal"])
public_router = APIRouter(prefix="/buyer-portal", tags=["buyer-portal-public"])


class CreatePortalBody(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    frameworks_filter_json: str | None = None


@router.post("/portals")
def create_portal(
    body: CreatePortalBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    p = bps.create_portal(
        db,
        session["workspace_id"],
        body.display_name,
        body.frameworks_filter_json,
    )
    db.commit()
    return p


@router.get("/portals")
def list_portals(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"portals": bps.list_portals(db, session["workspace_id"])}


class CaptureSnapshotBody(BaseModel):
    portal_id: int


@router.post("/snapshots/capture")
def capture_snapshot(
    body: CaptureSnapshotBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    portal = (
        db.query(BuyerPortal)
        .filter(
            BuyerPortal.id == body.portal_id,
            BuyerPortal.workspace_id == session["workspace_id"],
        )
        .first()
    )
    if not portal:
        raise HTTPException(status_code=404, detail="Portal not found")
    out = bps.capture_snapshot(db, portal)
    db.commit()
    return out


@router.get("/snapshots/{portal_id}")
def list_snapshots(
    portal_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {
        "snapshots": bps.list_snapshots(db, session["workspace_id"], portal_id),
    }


@router.get("/escalations")
def list_escalations(
    status: str | None = None,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"escalations": bps.list_escalations(db, session["workspace_id"], status)}


class UpdateEscalationBody(BaseModel):
    status: str | None = None
    seller_notes: str | None = None


@router.patch("/escalations/{escalation_id}")
def patch_escalation(
    escalation_id: int,
    body: UpdateEscalationBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    out = bps.update_escalation(
        db,
        escalation_id,
        session["workspace_id"],
        status=body.status,
        seller_notes=body.seller_notes,
    )
    if not out:
        raise HTTPException(status_code=404, detail="Escalation not found")
    db.commit()
    return out


@router.get("/subscriptions/{portal_id}")
def list_subs(
    portal_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"subscriptions": bps.list_subscriptions(db, session["workspace_id"], portal_id)}


# --- Public (token) ---


def _portal_from_token(db: Session, token: str):
    p = bps.get_portal_by_token(db, token)
    if not p:
        raise HTTPException(status_code=404, detail="Invalid or inactive portal token")
    return p


@public_router.get("/{token}/manifest")
def public_manifest(token: str, db: Session = Depends(get_db)):
    p = _portal_from_token(db, token)
    return bps.capabilities_manifest(p)


class InstantMatchBody(BaseModel):
    questions: list[str] = Field(..., min_length=1)


@public_router.post("/{token}/instant-match")
def public_instant_match(
    token: str,
    body: InstantMatchBody,
    db: Session = Depends(get_db),
):
    p = _portal_from_token(db, token)
    return {
        "matches": bps.match_questions(db, p.workspace_id, body.questions),
    }


@public_router.get("/{token}/changes")
def public_changes(token: str, db: Session = Depends(get_db)):
    p = _portal_from_token(db, token)
    summary = bps.get_latest_change_summary(db, p)
    if summary is None:
        return {"summary": None, "message": "Need at least two snapshots to compute changes"}
    return {"summary": summary}


class PublicEscalationBody(BaseModel):
    buyer_email: str
    escalation_type: str
    message: str
    question_snippet: str | None = None
    answer_id: int | None = None


@public_router.post("/{token}/escalations")
def public_escalation(
    token: str,
    body: PublicEscalationBody,
    db: Session = Depends(get_db),
):
    p = _portal_from_token(db, token)
    out = bps.create_escalation(
        db,
        p.workspace_id,
        p.id,
        body.buyer_email,
        body.escalation_type,
        body.message,
        question_snippet=body.question_snippet,
        answer_id=body.answer_id,
    )
    db.commit()
    return out


class SatisfactionBody(BaseModel):
    questionnaire_id: int | None = None
    accepted_without_edits: bool | None = None
    follow_up_count: int | None = None
    cycle_hours: float | None = None
    deal_closed: bool | None = None
    extra_json: str | None = None


@public_router.post("/{token}/satisfaction")
def public_satisfaction(
    token: str,
    body: SatisfactionBody,
    db: Session = Depends(get_db),
):
    p = _portal_from_token(db, token)
    out = bps.record_satisfaction(
        db,
        p.workspace_id,
        p.id,
        questionnaire_id=body.questionnaire_id,
        accepted_without_edits=body.accepted_without_edits,
        follow_up_count=body.follow_up_count,
        cycle_hours=body.cycle_hours,
        deal_closed=body.deal_closed,
        extra_json=body.extra_json,
    )
    db.commit()
    return out


class SubscribeBody(BaseModel):
    email: str
    frameworks_json: str | None = None


@public_router.post("/{token}/subscribe")
def public_subscribe(
    token: str,
    body: SubscribeBody,
    db: Session = Depends(get_db),
):
    p = _portal_from_token(db, token)
    out = bps.subscribe_changes(db, p.id, body.email, body.frameworks_json)
    db.commit()
    return out
