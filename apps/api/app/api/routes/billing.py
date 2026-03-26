"""Stripe billing API routes."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Subscription, User, Workspace

FREE_TRIAL_END = datetime(2026, 4, 5, 23, 59, 59, tzinfo=timezone.utc)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _get_stripe():
    """Lazy-import and configure stripe so the module is optional at import time."""
    import stripe

    s = get_settings()
    if not s.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
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
    """Create a Stripe Checkout Session for the Pro plan. Returns the checkout URL."""
    stripe = _get_stripe()
    s = get_settings()
    price_id = s.stripe_price_id
    if body.interval == "annual" and s.stripe_annual_price_id:
        price_id = s.stripe_annual_price_id
    if not price_id:
        raise HTTPException(status_code=503, detail="Stripe price not configured")

    user_id = session.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    workspace_id = body.workspace_id or session.get("workspace_id", 0)

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
        "metadata": {"user_id": str(user_id), "workspace_id": str(workspace_id)},
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
        metadata={"user_id": str(user_id), "workspace_id": str(workspace_id)},
        subscription_data=sub_data,
    )

    return {"checkout_url": checkout_session.url, "session_id": checkout_session.id}


@router.get("/subscription")
async def get_subscription(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Return the current workspace's subscription status."""
    workspace_id = session.get("workspace_id", 0)
    sub = db.query(Subscription).filter(
        Subscription.workspace_id == workspace_id,
    ).order_by(Subscription.created_at.desc()).first()

    if not sub:
        return {"status": "none", "plan": None}

    return {
        "status": sub.status,
        "plan": sub.plan,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
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
    workspace_id = session.get("workspace_id", 0)

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
    """Handle Stripe webhook events. No auth — verified by signature."""
    stripe = _get_stripe()
    s = get_settings()

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header or not s.stripe_webhook_secret:
        raise HTTPException(status_code=400, detail="Missing signature or webhook secret")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, s.stripe_webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.warning("Stripe webhook construct_event failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("type", "")
    data_obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data_obj, db)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data_obj, db)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data_obj, db)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data_obj, db)
    else:
        logger.info("Unhandled Stripe event type: %s", event_type)

    return JSONResponse({"received": True})


def _handle_checkout_completed(data: dict, db: Session):
    """Process checkout.session.completed — create or update subscription record."""
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")
    metadata = data.get("metadata", {})
    user_id = int(metadata.get("user_id", 0))
    workspace_id = int(metadata.get("workspace_id", 0))

    if not customer_id or not subscription_id:
        logger.warning("checkout.session.completed missing customer or subscription")
        return

    existing = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription_id,
    ).first()

    if existing:
        existing.status = "active"
        existing.updated_at = datetime.now(timezone.utc)
    else:
        sub = Subscription(
            workspace_id=workspace_id,
            user_id=user_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            status="active",
            plan="pro",
        )
        db.add(sub)

    db.commit()

    try:
        from app.services import credit_service
        credit_service.get_or_create_ledger(db, workspace_id)
        db.commit()
    except Exception:
        logger.warning("Failed to initialize credit ledger for workspace %s", workspace_id, exc_info=True)

    logger.info("Subscription created/activated: workspace=%s customer=%s", workspace_id, customer_id)


def _handle_subscription_updated(data: dict, db: Session):
    """Process customer.subscription.updated — sync status and period."""
    sub_id = data.get("id")
    if not sub_id:
        return

    sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
    if not sub:
        logger.warning("subscription.updated for unknown sub_id=%s", sub_id)
        return

    sub.status = data.get("status", sub.status)
    sub.cancel_at_period_end = 1 if data.get("cancel_at_period_end") else 0

    period = data.get("current_period_start")
    if period:
        sub.current_period_start = datetime.fromtimestamp(period, tz=timezone.utc)
    period_end = data.get("current_period_end")
    if period_end:
        sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)

    sub.updated_at = datetime.now(timezone.utc)
    db.commit()


def _handle_subscription_deleted(data: dict, db: Session):
    """Process customer.subscription.deleted — mark cancelled."""
    sub_id = data.get("id")
    if not sub_id:
        return

    sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
    if sub:
        sub.status = "canceled"
        sub.updated_at = datetime.now(timezone.utc)
        db.commit()


def _handle_payment_failed(data: dict, db: Session):
    """Process invoice.payment_failed — mark past_due."""
    sub_id = data.get("subscription")
    if not sub_id:
        return

    sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
    if sub and sub.status == "active":
        sub.status = "past_due"
        sub.updated_at = datetime.now(timezone.utc)
        db.commit()
