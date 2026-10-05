"""Stripe payment logic (2026-10-05). Stripe itself is mocked out at
app.services.stripe_gateway; webhook signatures are checked for real."""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.models.booking import Booking
from app.services import payment_service
from app.services.stripe_gateway import IntentInfo


def make_booking(**overrides) -> Booking:
    values = dict(
        id="booking-1",
        user_id="user-1",
        drone_id="drone-1",
        location_id="loc-1",
        pickup_time=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        rental_duration=1,
        rental_type="daily",
        status="pending_payment",
        payment_status="unpaid",
        total_cost=Decimal("35.00"),
    )
    values.update(overrides)
    booking = Booking(**values)
    booking.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    return booking


def intent(status="succeeded", amount=3500, charge="ch_1", intent_id="pi_1") -> IntentInfo:
    return IntentInfo(
        id=intent_id,
        status=status,
        client_secret=f"{intent_id}_secret",
        amount=amount,
        amount_received=amount if status == "succeeded" else 0,
        latest_charge_id=charge,
        metadata={"booking_id": "booking-1"},
    )


def fake_db(scalar=None):
    """AsyncSession stand-in: every execute() finds `scalar` (default nothing)."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    db.get = AsyncMock(return_value=None)
    return db


def settings(**overrides):
    values = dict(
        payments_enabled=True,
        stripe_secret_key="sk_test_x",
        stripe_publishable_key="pk_test_x",
        stripe_webhook_secret="whsec_test",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


GW = "app.services.payment_service.stripe_gateway"


class AmountTests(TestCase):
    def test_dollars_to_cents(self):
        self.assertEqual(payment_service.amount_cents(Decimal("35.00")), 3500)
        self.assertEqual(payment_service.amount_cents(Decimal("1")), 100)
        self.assertEqual(payment_service.amount_cents(Decimal("12.345")), 1235)

    def test_fallback_fee_matches_stripe_standard_pricing(self):
        self.assertEqual(payment_service.estimated_fee_cents(3500), 132)  # $1.32
        self.assertEqual(payment_service.estimated_fee_cents(100), 33)

    def test_pending_hold_expiry(self):
        fresh = make_booking()
        stale = make_booking(created_at=datetime.now(timezone.utc) - timedelta(minutes=16))
        self.assertFalse(payment_service.is_pending_payment_expired(fresh))
        self.assertTrue(payment_service.is_pending_payment_expired(stale))
        self.assertFalse(
            payment_service.is_pending_payment_expired(
                make_booking(status="reserved", created_at=stale.created_at)
            )
        )


class ActivationTests(IsolatedAsyncioTestCase):
    async def test_paid_booking_becomes_reserved(self):
        booking = make_booking()
        await payment_service.activate_paid_booking(booking, intent(), fake_db())
        self.assertEqual(booking.status, "reserved")
        self.assertEqual(booking.payment_status, "paid")
        self.assertEqual(booking.amount_paid_cents, 3500)

    async def test_paid_booking_goes_ready_when_locker_holds_passcode(self):
        unit = SimpleNamespace(
            current_passcode="1234",
            smiota_locker_name="3",
            smiota_metadata={"pending_deposit_courier_code": "c", "pending_deposit_object_id": "o"},
        )
        booking = make_booking()
        await payment_service.activate_paid_booking(booking, intent(), fake_db(scalar=unit))
        self.assertEqual(booking.status, "ready_for_pickup")
        self.assertEqual(booking.smiota_passcode, "1234")

    async def test_activation_is_idempotent(self):
        booking = make_booking()
        db = fake_db()
        await payment_service.activate_paid_booking(booking, intent(), db)
        await payment_service.activate_paid_booking(booking, intent(), db)
        self.assertEqual(booking.status, "reserved")

    async def test_payment_after_hold_lapsed_is_fully_refunded(self):
        booking = make_booking(status="cancelled", payment_status="canceled")
        with patch(f"{GW}.create_refund", return_value="re_1") as refund:
            await payment_service.activate_paid_booking(booking, intent(), fake_db())
        refund.assert_called_once_with(payment_intent_id="pi_1", amount_cents=3500, booking_id="booking-1")
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(booking.payment_status, "refunded")
        self.assertEqual(booking.refunded_amount_cents, 3500)


class CancellationRefundTests(IsolatedAsyncioTestCase):
    async def test_refund_is_amount_minus_actual_stripe_fee(self):
        booking = make_booking(
            status="reserved", payment_status="paid", amount_paid_cents=3500,
            stripe_payment_intent_id="pi_1",
        )
        with patch(f"{GW}.retrieve_payment_intent", return_value=intent()), \
             patch(f"{GW}.get_charge_fee_cents", return_value=132), \
             patch(f"{GW}.create_refund", return_value="re_1") as refund:
            await payment_service.refund_for_cancellation(booking, fake_db())
        refund.assert_called_once_with(payment_intent_id="pi_1", amount_cents=3368, booking_id="booking-1")
        self.assertEqual(booking.stripe_fee_cents, 132)
        self.assertEqual(booking.refunded_amount_cents, 3368)
        self.assertEqual(booking.payment_status, "refunded")

    async def test_one_dollar_test_rental_refund(self):
        booking = make_booking(
            status="reserved", payment_status="paid", amount_paid_cents=100,
            stripe_payment_intent_id="pi_1", total_cost=Decimal("1.00"),
        )
        with patch(f"{GW}.retrieve_payment_intent", return_value=intent(amount=100)), \
             patch(f"{GW}.get_charge_fee_cents", return_value=33), \
             patch(f"{GW}.create_refund", return_value="re_1") as refund:
            await payment_service.refund_for_cancellation(booking, fake_db())
        refund.assert_called_once_with(payment_intent_id="pi_1", amount_cents=67, booking_id="booking-1")

    async def test_uses_estimate_when_fee_not_reported_yet(self):
        booking = make_booking(
            status="reserved", payment_status="paid", amount_paid_cents=3500,
            stripe_payment_intent_id="pi_1",
        )
        with patch(f"{GW}.retrieve_payment_intent", return_value=intent()), \
             patch(f"{GW}.get_charge_fee_cents", return_value=None), \
             patch(f"{GW}.create_refund", return_value="re_1") as refund:
            await payment_service.refund_for_cancellation(booking, fake_db())
        refund.assert_called_once_with(payment_intent_id="pi_1", amount_cents=3368, booking_id="booking-1")

    async def test_unpaid_booking_is_not_refunded(self):
        booking = make_booking(status="reserved", payment_status=None)
        with patch(f"{GW}.create_refund") as refund:
            await payment_service.refund_for_cancellation(booking, fake_db())
        refund.assert_not_called()

    async def test_stripe_failure_raises_and_leaves_booking_paid(self):
        import stripe

        booking = make_booking(
            status="reserved", payment_status="paid", amount_paid_cents=3500,
            stripe_payment_intent_id="pi_1", stripe_fee_cents=132,
        )
        with patch(f"{GW}.create_refund", side_effect=stripe.APIConnectionError("down")):
            with self.assertRaises(HTTPException) as ctx:
                await payment_service.refund_for_cancellation(booking, fake_db())
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(booking.payment_status, "paid")


class AbandonCheckoutTests(IsolatedAsyncioTestCase):
    async def test_abandon_cancels_intent_and_booking(self):
        booking = make_booking(stripe_payment_intent_id="pi_1")
        with patch(f"{GW}.retrieve_payment_intent", return_value=intent(status="requires_payment_method")), \
             patch(f"{GW}.cancel_payment_intent", return_value=intent(status="canceled")) as cancel:
            await payment_service.abandon_pending_checkout(booking, fake_db())
        cancel.assert_called_once_with("pi_1")
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(booking.payment_status, "canceled")

    async def test_abandon_activates_if_stripe_says_paid(self):
        booking = make_booking(stripe_payment_intent_id="pi_1")
        with patch(f"{GW}.retrieve_payment_intent", return_value=intent()), \
             patch(f"{GW}.cancel_payment_intent") as cancel:
            await payment_service.abandon_pending_checkout(booking, fake_db())
        cancel.assert_not_called()
        self.assertEqual(booking.status, "reserved")

    async def test_processing_payment_keeps_hold(self):
        booking = make_booking(stripe_payment_intent_id="pi_1")
        with patch(f"{GW}.retrieve_payment_intent", return_value=intent(status="processing")):
            await payment_service.abandon_pending_checkout(booking, fake_db())
        self.assertEqual(booking.status, "pending_payment")

    async def test_expire_never_raises_on_stripe_outage(self):
        import stripe

        booking = make_booking(
            stripe_payment_intent_id="pi_1",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        with patch(f"{GW}.retrieve_payment_intent", side_effect=stripe.APIConnectionError("down")):
            await payment_service.expire_if_stale(booking, fake_db())
        self.assertEqual(booking.status, "pending_payment")


class CheckoutTests(IsolatedAsyncioTestCase):
    async def test_checkout_refused_when_payments_disabled(self):
        with patch("app.services.payment_service.get_settings", return_value=settings(payments_enabled=False)):
            with self.assertRaises(HTTPException) as ctx:
                await payment_service.start_checkout("booking-1", SimpleNamespace(id="user-1"), fake_db())
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_checkout_creates_intent_for_server_price(self):
        booking = make_booking(total_cost=Decimal("1.00"))
        user = SimpleNamespace(id="user-1", email="a@b.c", first_name="A", last_name="B",
                               stripe_customer_id="cus_1")
        with patch("app.services.payment_service.get_settings", return_value=settings()), \
             patch("app.services.payment_service._get_owned_booking", AsyncMock(return_value=booking)), \
             patch(f"{GW}.create_payment_intent", return_value=intent(status="requires_payment_method", amount=100)) as create:
            response = await payment_service.start_checkout("booking-1", user, fake_db())
        self.assertEqual(create.call_args.kwargs["amount_cents"], 100)
        self.assertEqual(create.call_args.kwargs["customer_id"], "cus_1")
        self.assertEqual(booking.stripe_payment_intent_id, "pi_1")
        self.assertEqual(response.client_secret, "pi_1_secret")
        self.assertEqual(response.publishable_key, "pk_test_x")

    async def test_confirm_refuses_unpaid_intent(self):
        booking = make_booking(stripe_payment_intent_id="pi_1")
        with patch("app.services.payment_service._get_owned_booking", AsyncMock(return_value=booking)), \
             patch(f"{GW}.retrieve_payment_intent", return_value=intent(status="requires_payment_method")):
            with self.assertRaises(HTTPException) as ctx:
                await payment_service.confirm_payment("booking-1", SimpleNamespace(id="user-1"), fake_db())
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertEqual(booking.status, "pending_payment")

    async def test_confirm_activates_succeeded_intent(self):
        booking = make_booking(stripe_payment_intent_id="pi_1")
        with patch("app.services.payment_service._get_owned_booking", AsyncMock(return_value=booking)), \
             patch(f"{GW}.retrieve_payment_intent", return_value=intent()):
            await payment_service.confirm_payment("booking-1", SimpleNamespace(id="user-1"), fake_db())
        self.assertEqual(booking.status, "reserved")


def signed(payload: dict, secret: str = "whsec_test") -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def succeeded_event(event_id="evt_1"):
    return {
        "id": event_id,
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {"object": {
            "id": "pi_1", "object": "payment_intent", "status": "succeeded",
            "amount": 3500, "amount_received": 3500, "latest_charge": "ch_1",
            "metadata": {"booking_id": "booking-1"},
        }},
    }


class WebhookTests(IsolatedAsyncioTestCase):
    async def test_rejects_bad_signature(self):
        body, _ = signed(succeeded_event())
        with patch("app.services.payment_service.get_settings", return_value=settings()):
            with self.assertRaises(HTTPException) as ctx:
                await payment_service.handle_stripe_webhook(body, "t=1,v1=bad", fake_db())
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_rejects_when_secret_not_configured(self):
        body, header = signed(succeeded_event())
        with patch("app.services.payment_service.get_settings", return_value=settings(stripe_webhook_secret=None)):
            with self.assertRaises(HTTPException) as ctx:
                await payment_service.handle_stripe_webhook(body, header, fake_db())
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_succeeded_event_activates_booking(self):
        booking = make_booking(stripe_payment_intent_id="pi_1")
        db = fake_db()
        first = MagicMock(); first.scalar_one_or_none.return_value = booking
        none = MagicMock(); none.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[first, none])  # booking lookup, locker lookup
        body, header = signed(succeeded_event())
        with patch("app.services.payment_service.get_settings", return_value=settings()):
            response = await payment_service.handle_stripe_webhook(body, header, db)
        self.assertEqual(response.outcome, "processed")
        self.assertEqual(booking.status, "reserved")
        self.assertEqual(booking.amount_paid_cents, 3500)

    async def test_duplicate_event_is_skipped(self):
        db = fake_db()
        db.get = AsyncMock(return_value=object())  # already recorded
        body, header = signed(succeeded_event())
        with patch("app.services.payment_service.get_settings", return_value=settings()):
            response = await payment_service.handle_stripe_webhook(body, header, db)
        self.assertTrue(response.duplicate)
        db.execute.assert_not_called()
