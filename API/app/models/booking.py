"""
app/models/booking.py
----------------------
ORM model for the `bookings` table.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.booking_lifecycle import BOOKING_STATUSES
from app.db.base import Base


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    drone_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("drones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("locker_locations.id", ondelete="CASCADE"),
        nullable=False,
    )
    pickup_time: Mapped[str] = mapped_column(String(50), nullable=False)
    rental_duration: Mapped[int] = mapped_column(Integer, nullable=False)
    rental_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="reserved", server_default="reserved"
    )
    total_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Smiota locker data (populated via webhook)
    smiota_object_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    smiota_passcode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    smiota_locker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smiota_courier_code: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ready_for_pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locker_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    case_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    before_photos_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    in_use_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    after_photos_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_locker_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_video_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN {BOOKING_STATUSES}",
            name="ck_booking_status",
        ),
        CheckConstraint(
            "rental_type IN ('hourly', 'daily')", name="ck_booking_rental_type"
        ),
        CheckConstraint("rental_duration > 0", name="ck_booking_rental_duration"),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="bookings")  # noqa: F821
    drone: Mapped["Drone"] = relationship("Drone", back_populates="bookings")  # noqa: F821
    location: Mapped["LockerLocation"] = relationship(  # noqa: F821
        "LockerLocation", back_populates="bookings"
    )
    damage_report: Mapped["DamageReport | None"] = relationship(  # noqa: F821
        "DamageReport", back_populates="booking", uselist=False
    )
