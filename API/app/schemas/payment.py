"""
app/schemas/payment.py
-----------------------
Schemas for the Stripe checkout endpoints.
"""

from datetime import datetime

from pydantic import BaseModel


class PaymentIntentResponse(BaseModel):
    booking_id: str
    payment_intent_id: str
    # Handed to the app's Stripe PaymentSheet. Lets the client confirm this
    # one payment and nothing else; it is not a secret key.
    client_secret: str
    amount_cents: int
    currency: str
    # Stripe publishable key (pk_test_... / pk_live_...). Served from the
    # backend so switching test -> live is a Render change, not an app update.
    publishable_key: str
    payment_intent_status: str
    # When the drone hold lapses if payment isn't completed.
    expires_at: datetime


class StripeWebhookResponse(BaseModel):
    received: bool = True
    duplicate: bool = False
    outcome: str = "processed"
