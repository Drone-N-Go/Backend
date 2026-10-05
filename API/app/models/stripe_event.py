"""
app/models/stripe_event.py
---------------------------
One row per Stripe webhook event we have processed. The event id is the
primary key, so a replayed or duplicate delivery is detected and skipped.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # Stripe event id (evt_...)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    booking_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="processed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
