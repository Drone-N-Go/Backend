"""
app/services/stripe_gateway.py
-------------------------------
The only module that talks to Stripe. Everything here is a thin, synchronous
wrapper around the official SDK, called from async code via
asyncio.to_thread() in payment_service. Keeping it this small makes the
payment logic testable with this module mocked out.

Only long-stable API fields are used (amount, currency, customer,
setup_future_usage, automatic_payment_methods, latest_charge,
balance_transaction.fee), so the pinned SDK version can move without
touching this file.
"""

from __future__ import annotations

from dataclasses import dataclass

import stripe

from app.core.config import get_settings


@dataclass
class IntentInfo:
    id: str
    status: str
    client_secret: str | None
    amount: int
    amount_received: int
    latest_charge_id: str | None
    metadata: dict


def _client() -> stripe.StripeClient:
    return stripe.StripeClient(get_settings().require_stripe_secret_key())


def _as_dict(obj) -> dict:
    # StripeObject is not a dict in current SDKs; to_dict() converts it
    # (recursively). Plain dicts (used in tests) pass straight through.
    return obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)


def _intent_info(intent) -> IntentInfo:
    intent = _as_dict(intent)
    latest_charge = intent.get("latest_charge")
    if latest_charge is not None and not isinstance(latest_charge, str):
        latest_charge = latest_charge.get("id")
    return IntentInfo(
        id=intent["id"],
        status=intent["status"],
        client_secret=intent.get("client_secret"),
        amount=int(intent.get("amount") or 0),
        amount_received=int(intent.get("amount_received") or 0),
        latest_charge_id=latest_charge,
        metadata=dict(intent.get("metadata") or {}),
    )


def create_customer(*, email: str, name: str, user_id: str) -> str:
    customer = _client().v1.customers.create(
        params={"email": email, "name": name, "metadata": {"user_id": user_id}},
        options={"idempotency_key": f"user-{user_id}-customer"},
    )
    return _as_dict(customer)["id"]


def create_payment_intent(
    *,
    amount_cents: int,
    customer_id: str,
    booking_id: str,
    user_id: str,
    description: str,
) -> IntentInfo:
    intent = _client().v1.payment_intents.create(
        params={
            "amount": amount_cents,
            "currency": "usd",
            "customer": customer_id,
            # Saves the card / Apple Pay used to the Customer, so damage or
            # late-return fees can be charged after the rental.
            "setup_future_usage": "off_session",
            # Card and Apple Pay only in practice; anything that would send
            # the renter off to a bank/redirect page is excluded.
            "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
            "description": description,
            "metadata": {"booking_id": booking_id, "user_id": user_id},
        },
        options={"idempotency_key": f"booking-{booking_id}-payment-intent"},
    )
    return _intent_info(intent)


def retrieve_payment_intent(intent_id: str) -> IntentInfo:
    return _intent_info(_client().v1.payment_intents.retrieve(intent_id))


def cancel_payment_intent(intent_id: str) -> IntentInfo:
    return _intent_info(_client().v1.payment_intents.cancel(intent_id))


def get_charge_fee_cents(charge_id: str) -> int | None:
    """Stripe's actual processing fee for a charge, or None if Stripe has not
    created the balance transaction yet."""
    charge = _as_dict(_client().v1.charges.retrieve(
        charge_id, params={"expand": ["balance_transaction"]}
    ))
    balance_transaction = charge.get("balance_transaction")
    if not balance_transaction or isinstance(balance_transaction, str):
        return None
    return int(balance_transaction["fee"])


def create_refund(*, payment_intent_id: str, amount_cents: int, booking_id: str) -> str:
    refund = _client().v1.refunds.create(
        params={
            "payment_intent": payment_intent_id,
            "amount": amount_cents,
            "metadata": {"booking_id": booking_id, "reason": "renter_cancelled"},
        },
        options={"idempotency_key": f"booking-{booking_id}-cancel-refund"},
    )
    return _as_dict(refund)["id"]


def construct_event(payload: bytes, sig_header: str | None, secret: str):
    """Verifies the Stripe-Signature header and returns the event as a plain
    dict. Raises stripe.SignatureVerificationError (bad signature) or
    ValueError (bad body)."""
    return _as_dict(stripe.Webhook.construct_event(payload, sig_header, secret))
