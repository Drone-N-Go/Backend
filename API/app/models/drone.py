"""
app/models/drone.py
--------------------
ORM model for the `drones` table.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Drone(Base):
    __tablename__ = "drones"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="available", server_default="available"
    )
    assigned_locker_location_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("locker_locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    daily_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
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
            "status IN ('available', 'rented', 'damaged', 'maintenance')",
            name="ck_drone_status",
        ),
        CheckConstraint("hourly_rate > 0", name="ck_drone_hourly_rate"),
        CheckConstraint("daily_rate > 0", name="ck_drone_daily_rate"),
    )

    # Relationships
    assigned_location: Mapped["LockerLocation | None"] = relationship(  # noqa: F821
        "LockerLocation", back_populates="drones"
    )
    bookings: Mapped[list["Booking"]] = relationship(  # noqa: F821
        "Booking", back_populates="drone", lazy="select"
    )
