"""
app/services/payment_service.py
--------------------------------
Stripe checkout for bookings (added 2026-10-05).

Flow, when PAYMENTS_ENABLED is on:
  1. POST /api/bookings                      -> booking created as `pending_payment`,
                                                drone held for PENDING_PAYMENT_TTL_MINUTES.
  2. POST /api/bookings/{id}/payment-intent  -> creates (or re-uses) a Stripe
                                                PaymentIntent; the app shows Stripe's
                                                PaymentSheet (Apple Pay + card).
  3. POST /api/bookings/{id}/payment/confirm -> the app's fast path after the sheet
                                                closes. The backend asks Stripe itself
                                                whether the payment succeeded; the app's
                                                word is never trusted.
     POST /api/webhooks/stripe               -> Stripe's own notification. Same effect
                                                as step 3; covers the app being closed
                                                right after paying.
  Either 3 path moves the booking to `reserved` (or `ready_for_pickup` if the
  drone's locker already holds a passcode). Both are idempotent.

Cancellation inside the allowed window refunds the amount paid minus Stripe's
actual processing fee for that charge (owner policy, 2026-10-05).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import stripe
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.booking_lifecycle import PENDING_PAYMENT_TTL_MINUTES
from app.core.config import get_settings
from app.models.booking import Booking
from app.models.drone import Drone
from app.models.locker_unit import LockerUnit
from app.models.stripe_event import StripeEvent
from app.models.user import User
from app.schemas.payment import PaymentIntentResponse, StripeWebhookResponse
from app.services import stripe_gateway
from app.services.stripe_gateway import IntentInfo

logger = logging.getLogger(__name__)

PENDING_PAYMENT_TTL = timedelta(minutes=PENDING_PAYMENT_TTL_MINUTES)

# PaymentIntent statuses that can still be cancelled. `processing` cannot be
# cancelled and may still succeed, so a booking in that state is left alone.
CANCELLABLE_INTENT_STATUSES = {
    "requires_payment_method",
    "requires_confirmation",
    "requires_action",
}

# Used only if Stripe has not reported the real fee for a charge yet
# (standard US card pricing: 2.9% + 30c). Logged whenever it is used.
FALLBACK_FEE_RATE = Decimal("0.029")
FALLBACK_FEE_FIXED_CENTS = 30


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def payments_enabled() -> bool:
    return get_settings().payments_enabled


def amount_cents(total_cost: Decimal) -> int:
    return int((Decimal(str(total_cost)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimated_fee_cents(amount: int) -> int:
    return int(
        (Decimal(amount) * FALLBACK_FEE_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    ) + FALLBACK_FEE_FIXED_CENTS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def pending_payment_expires_at(booking: Booking) -> datetime:
    return _aware(booking.created_at) + PENDING_PAYMENT_TTL


def is_pending_payment_expired(booking: Booking) -> bool:
    return booking.status == "pending_payment" and _now() >= pending_payment_expires_at(booking)


async def _stripe(fn, *args, **kwargs):
    """Run a blocking Stripe SDK call off the event loop, translating
    failures into clean HTTP errors."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except stripe.StripeError as exc:
        logger.error("Stripe call %s failed: %s", getattr(fn, "__name__", fn), exc)
        message = getattr(exc, "user_message", None) or "Please try again."
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Payment provider error: {message}",
        ) from exc
    except ValueError as exc:  # missing STRIPE_SECRET_KEY
        logger.error("Stripe is not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments are not configured on the server.",
        ) from exc


def _require_checkout_configured() -> str:
    settings = get_settings()
    if not settings.payments_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payments are not enabled.",
        )
    if not settings.stripe_secret_key or not settings.stripe_publishable_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments are not configured on the server.",
        )
    return settings.stripe_publishable_key


async def _free_drone(booking: Booking, db: AsyncSession) -> None:
    result = await db.execute(select(Drone).where(Drone.id == booking.drone_id))
    drone = result.scalar_one_or_none()
    if drone and drone.status == "rented":
        drone.status = "available"
        db.add(drone)


async def _get_owned_booking(booking_id: str, user: User, db: AsyncSession) -> Booking:
    # Imported here: booking_service imports this module too.
    from app.services.booking_service import _assert_current_user_booking, _get_booking_or_404

    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, user)
    return booking


# --------------------------------------------------------------------------- #
# State changes
# --------------------------------------------------------------------------- #

async def activate_paid_booking(booking: Booking, intent: IntentInfo, db: AsyncSession) -> Booking:
    """Record a succeeded payment and release the booking into the normal
    lifecycle. Safe to call more than once for the same payment."""
    paid_amount = intent.amount_received or intent.amount

    if booking.status == "pending_payment":
        booking.payment_status = "paid"
        booking.amount_paid_cents = paid_amount
        booking.paid_at = _now()
        booking.status = "reserved"

        # If the drone's locker already holds a passcode (restock deposit, see
        # webhook_service._handle_restock_deposit), the booking can go straight
        # to ready_for_pickup. This used to happen at booking creation; it now
        # waits until the booking is paid so an unpaid booking never exposes
        # a locker code.
        unit_result = await db.execute(
            select(LockerUnit).where(LockerUnit.current_drone_id == booking.drone_id)
        )
        locker_unit = unit_result.scalar_one_or_none()
        if locker_unit and locker_unit.current_passcode:
            metadata = locker_unit.smiota_metadata or {}
            booking.smiota_passcode = locker_unit.current_passcode
            booking.smiota_locker_name = locker_unit.smiota_locker_name
            booking.smiota_courier_code = metadata.get("pending_deposit_courier_code")
            booking.smiota_object_id = metadata.get("pending_deposit_object_id")
            booking.status = "ready_for_pickup"
            booking.ready_for_pickup_at = _now()

        db.add(booking)
        await db.flush()
        logger.info("Booking %s paid (%s cents) -> %s", booking.id, paid_amount, booking.status)
        return booking

    if booking.status == "cancelled" and booking.payment_status not in {"paid", "refunded"}:
        # The payment completed after the checkout hold had already lapsed
        # and the drone was released. The renter has no booking, so the
        # money goes straight back in full.
        refund_id = await _stripe(
            stripe_gateway.create_refund,
            payment_intent_id=intent.id,
            amount_cents=paid_amount,
            booking_id=booking.id,
        )
        booking.amount_paid_cents = paid_amount
        booking.paid_at = _now()
        booking.refunded_amount_cents = paid_amount
        booking.stripe_refund_id = refund_id
        booking.payment_status = "refunded"
        db.add(booking)
        await db.flush()
        logger.warning(
            "Booking %s was paid after its checkout hold lapsed; fully refunded (%s)",
            booking.id,
            refund_id,
        )
    return booking


async def abandon_pending_checkout(booking: Booking, db: AsyncSession) -> Booking:
    """Cancel an unpaid checkout and release the drone. If Stripe reports the
    payment actually succeeded, the booking is activated instead."""
    if booking.status != "pending_payment":
        return booking

    if booking.stripe_payment_intent_id:
        intent = await _stripe(stripe_gateway.retrieve_payment_intent, booking.stripe_payment_intent_id)
        if intent.status == "succeeded":
            return await activate_paid_booking(booking, intent, db)
        if intent.status == "processing":
            # Can't cancel it and it may still succeed; keep the hold.
            return booking
        if intent.status in CANCELLABLE_INTENT_STATUSES:
            await _stripe(stripe_gateway.cancel_payment_intent, booking.stripe_payment_intent_id)

    from app.services.booking_service import _stamp_status_timestamp

    booking.status = "cancelled"
    booking.payment_status = "canceled"
    _stamp_status_timestamp(booking, "cancelled")
    db.add(booking)
    await _free_drone(booking, db)
    await db.flush()
    logger.info("Unpaid checkout for booking %s cancelled", booking.id)
    return booking


async def expire_if_stale(booking: Booking, db: AsyncSession) -> Booking:
    """Lazy expiry of an abandoned checkout (no background jobs exist in this
    backend, same approach as booking_service._auto_expire_if_overdue). Never
    raises: a Stripe outage must not break ordinary booking reads."""
    if not is_pending_payment_expired(booking):
        return booking
    try:
        return await abandon_pending_checkout(booking, db)
    except HTTPException as exc:
        logger.warning("Could not expire checkout for booking %s: %s", booking.id, exc.detail)
        return booking


async def refund_for_cancellation(booking: Booking, db: AsyncSession) -> None:
    """Refund a paid booking that the renter cancelled inside the allowed
    window: the amount paid minus Stripe's actual fee for that charge.
    Must run before the booking is marked cancelled, so a Stripe failure
    leaves the booking untouched and the renter can simply try again."""
    if booking.payment_status != "paid" or not booking.stripe_payment_intent_id:
        return

    paid = booking.amount_paid_cents or amount_cents(booking.total_cost)
    fee = booking.stripe_fee_cents
    if fee is None:
        intent = await _stripe(stripe_gateway.retrieve_payment_intent, booking.stripe_payment_intent_id)
        if intent.latest_charge_id:
            fee = await _stripe(stripe_gateway.get_charge_fee_cents, intent.latest_charge_id)
        if fee is None:
            fee = estimated_fee_cents(paid)
            logger.warning(
                "Stripe fee not available yet for booking %s; using estimate %s cents",
                booking.id,
                fee,
            )
        booking.stripe_fee_cents = fee

    refund_amount = max(0, paid - fee)
    if refund_amount > 0:
        booking.stripe_refund_id = await _stripe(
            stripe_gateway.create_refund,
            payment_intent_id=booking.stripe_payment_intent_id,
            amount_cents=refund_amount,
            booking_id=booking.id,
        )
    booking.refunded_amount_cents = refund_amount
    booking.payment_status = "refunded"
    db.add(booking)
    logger.info(
        "Booking %s cancelled: refunded %s of %s cents (Stripe fee %s)",
        booking.id,
        refund_amount,
        paid,
        fee,
    )


# --------------------------------------------------------------------------- #
# Checkout endpoints
# --------------------------------------------------------------------------- #

async def ensure_stripe_customer(user: User, db: AsyncSession) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer_id = await _stripe(
        stripe_gateway.create_customer,
        email=user.email,
        name=f"{user.first_name} {user.last_name}".strip(),
        user_id=user.id,
    )
    user.stripe_customer_id = customer_id
    db.add(user)
    await db.flush()
    return customer_id


async def start_checkout(booking_id: str, user: User, db: AsyncSession) -> PaymentIntentResponse:
    publishable_key = _require_checkout_configured()
    booking = await _get_owned_booking(booking_id, user, db)

    if booking.status != "pending_payment":
        if booking.payment_status == "paid":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="This booking is already paid.")
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This checkout has expired. Please start your booking again.",
        )

    if booking.stripe_payment_intent_id:
        intent = await _stripe(stripe_gateway.retrieve_payment_intent, booking.stripe_payment_intent_id)
        if intent.status == "succeeded":
            await activate_paid_booking(booking, intent, db)
        elif intent.status == "canceled":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="This checkout has expired. Please start your booking again.",
            )
    else:
        customer_id = await ensure_stripe_customer(user, db)
        intent = await _stripe(
            stripe_gateway.create_payment_intent,
            amount_cents=amount_cents(booking.total_cost),
            customer_id=customer_id,
            booking_id=booking.id,
            user_id=user.id,
            description=f"Drone & Go rental {booking.id[:8].upper()}",
        )
        booking.stripe_payment_intent_id = intent.id
        booking.payment_status = "unpaid"
        db.add(booking)
        await db.flush()

    if not intent.client_secret:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Payment provider error: missing client secret.")

    return PaymentIntentResponse(
        booking_id=booking.id,
        payment_intent_id=intent.id,
        client_secret=intent.client_secret,
        amount_cents=intent.amount,
        currency="usd",
        publishable_key=publishable_key,
        payment_intent_status=intent.status,
        expires_at=pending_payment_expires_at(booking),
    )


async def confirm_payment(booking_id: str, user: User, db: AsyncSession) -> Booking:
    """Server-verified confirmation. The client only says "I think I paid";
    the booking moves only if Stripe says the PaymentIntent succeeded."""
    booking = await _get_owned_booking(booking_id, user, db)
    if booking.status != "pending_payment":
        return booking  # already activated (e.g. by the webhook) or cancelled
    if not booking.stripe_payment_intent_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No payment has been started for this booking.")

    intent = await _stripe(stripe_gateway.retrieve_payment_intent, booking.stripe_payment_intent_id)
    if intent.status == "succeeded":
        return await activate_paid_booking(booking, intent, db)
    if intent.status == "processing":
        return booking  # still pending; the webhook will finish it
    raise HTTPException(
        status.HTTP_402_PAYMENT_REQUIRED,
        detail="Payment has not been completed.",
    )


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #

async def _booking_for_intent(intent: dict, db: AsyncSession) -> Booking | None:
    intent_id = intent.get("id")
    if intent_id:
        result = await db.execute(select(Booking).where(Booking.stripe_payment_intent_id == intent_id))
        booking = result.scalar_one_or_none()
        if booking:
            return booking
    booking_id = (intent.get("metadata") or {}).get("booking_id")
    if booking_id:
        result = await db.execute(select(Booking).where(Booking.id == booking_id))
        return result.scalar_one_or_none()
    return None


async def handle_stripe_webhook(
    payload: bytes, sig_header: str | None, db: AsyncSession
) -> StripeWebhookResponse:
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook secret is not configured.",
        )
    try:
        event = stripe_gateway.construct_event(payload, sig_header, secret)
    except (stripe.SignatureVerificationError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature.")

    event_id = event["id"]
    event_type = event["type"]
    if await db.get(StripeEvent, event_id) is not None:
        return StripeWebhookResponse(duplicate=True, outcome="duplicate")

    obj = (event.get("data") or {}).get("object") or {}
    booking: Booking | None = None
    outcome = "ignored"

    if event_type == "payment_intent.succeeded":
        booking = await _booking_for_intent(obj, db)
        if booking:
            await activate_paid_booking(booking, stripe_gateway._intent_info(obj), db)
            outcome = "processed"
        else:
            outcome = "unmatched"
    elif event_type == "payment_intent.payment_failed":
        booking = await _booking_for_intent(obj, db)
        logger.info("Payment failed for booking %s", booking.id if booking else "<unknown>")
        outcome = "processed"
    elif event_type == "charge.refunded":
        intent_id = obj.get("payment_intent")
        if intent_id:
            booking = await _booking_for_intent({"id": intent_id}, db)
        if booking:
            # Keeps the record right for refunds issued from the Stripe Dashboard too.
            booking.refunded_amount_cents = int(obj.get("amount_refunded") or 0)
            booking.payment_status = "refunded"
            db.add(booking)
            outcome = "processed"
        else:
            outcome = "unmatched"

    db.add(
        StripeEvent(
            id=event_id,
            event_type=event_type,
            booking_id=booking.id if booking else None,
            processing_status=outcome,
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent delivery of the same event got there first.
        await db.rollback()
        return StripeWebhookResponse(duplicate=True, outcome="duplicate")

    logger.info("Stripe event %s (%s): %s", event_id, event_type, outcome)
    return StripeWebhookResponse(outcome=outcome)
