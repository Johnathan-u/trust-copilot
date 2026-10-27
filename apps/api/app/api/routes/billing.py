"""Stripe billing API routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Subscription, User
from app.services.billing_provider import (
    first_fatal_message,
    price_and_plan_for_interval,
    process_stripe_webhook,
)
from app.services.billing_seams import principal_for_billing_session

# TC-24-002 owns trial length. This fixed date is intentionally unchanged.
FREE_TRIAL_END = datetime(2026, 4, 5, 23, 59, 59, tzinfo=timezone.utc)

router = APIRouter(prefix="/billing", tags=["billing"])


def _get_stripe():
    """Lazy-import and configure stripe so the module is optional at import time."""
    import stripe

    s = get_settings()
    if not s.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    blocked = first_fatal_message(s)
    if blocked:
        raise HTTPException(status_code=503, detail=blocked)
    stripe.api_key = s.stripe_secret_key
    return stripe


class CreateCheckoutBody(BaseModel):
    workspace_id: int | None = None
    interval: str = "monthly"


@router.post("/create-checkout-session")
async def create_checkout_session(
    body: CreateCheckoutBody,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Create a Stripe Checkout Session for the configured plan. Returns the checkout URL."""
    stripe = _get_stripe()
    s = get_settings()
    selected = price_and_plan_for_interval(s, body.interval)
    if not selected:
        raise HTTPException(status_code=503, detail="Stripe price not configured")
    plan_key, price_id = selected

    actor = principal_for_billing_session(session)
    user_id = actor.user_id
    user = db.query(User).filter(User.id == user_id).first() if user_id else None
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    workspace_id = body.workspace_id or actor.workspace_id or 0

    existing = db.query(Subscription).filter(
        Subscription.workspace_id == workspace_id,
        Subscription.status.in_(["active", "trialing"]),
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Workspace already has an active subscription")

    sub_row = db.query(Subscription).filter(
        Subscription.user_id == user_id,
    ).first()
    customer_id = sub_row.stripe_customer_id if sub_row else None

    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"user_id": str(user_id), "workspace_id": str(workspace_id)},
        )
        customer_id = customer.id

    frontend = s.frontend_url.rstrip("/")

    now = datetime.now(timezone.utc)
    trial_end_ts = int(FREE_TRIAL_END.timestamp()) if now < FREE_TRIAL_END else None

    sub_data: dict = {
        "metadata": {
            "user_id": str(user_id),
            "workspace_id": str(workspace_id),
            "plan": plan_key,
            "price_id": price_id,
        },
    }
    if trial_end_ts:
        sub_data["trial_end"] = trial_end_ts

    checkout_session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{frontend}/dashboard?checkout=success",
        cancel_url=f"{frontend}/checkout?checkout=cancelled",
        metadata={
            "user_id": str(user_id),
            "workspace_id": str(workspace_id),
            "plan": plan_key,
            "price_id": price_id,
        },
        subscription_data=sub_data,
    )

    return {"checkout_url": checkout_session.url, "session_id": checkout_session.id}


@router.get("/subscription")
async def get_subscription(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Return the current workspace's subscription status."""
    actor = principal_for_billing_session(session)
    workspace_id = actor.workspace_id or 0
    sub = db.query(Subscription).filter(
        Subscription.workspace_id == workspace_id,
    ).order_by(Subscription.created_at.desc()).first()

    if not sub:
        return {"status": "none", "plan": None}

    return {
        "status": sub.status,
        "plan": sub.plan,
        "current_period_end": (
            sub.current_period_end.isoformat() if sub.current_period_end else None
        ),
        "cancel_at_period_end": bool(sub.cancel_at_period_end),
    }


@router.post("/create-portal-session")
async def create_portal_session(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Create a Stripe Customer Portal session for managing billing."""
    stripe = _get_stripe()
    s = get_settings()
    actor = principal_for_billing_session(session)
    workspace_id = actor.workspace_id or 0

    sub = db.query(Subscription).filter(
        Subscription.workspace_id == workspace_id,
    ).first()
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")

    frontend = s.frontend_url.rstrip("/")
    portal = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{frontend}/dashboard/settings",
    )

    return {"portal_url": portal.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhooks. The raw body is verified before JSON is parsed."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    result = process_stripe_webhook(db, payload, sig_header, get_settings())
    return JSONResponse(status_code=result.status_code, content=result.body)
